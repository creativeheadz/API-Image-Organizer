import streamlit as st
import os
import sys
import hashlib
import sqlite3
import json
from PIL import Image, ExifTags
import requests
import subprocess
import time
from datetime import datetime
import math

# Configuration
st.set_page_config(page_title="AI Image Organizer", layout="wide")
DATABASE = 'image_database.sqlite'
UPLOAD_FOLDER = 'data/images'
THUMBNAIL_FOLDER = 'data/thumbnails'
OLLAMA_URL = 'http://192.168.1.246:11434/api/generate'  # Remote Ollama instance
PROGRESS_FILE = 'import_progress.json'

# Make sure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(THUMBNAIL_FOLDER, exist_ok=True)

# Test connection to Ollama
def test_ollama_connection():
    try:
        response = requests.get('http://192.168.1.246:11434/')
        if response.status_code == 200:
            return True
        return False
    except requests.exceptions.RequestException:
        return False

# Database functions
def init_db():
    with sqlite3.connect(DATABASE) as conn:
        conn.execute('''
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            original_path TEXT NOT NULL,
            hash TEXT UNIQUE NOT NULL,
            thumbnail_path TEXT NOT NULL,
            tags TEXT DEFAULT '[]',
            date_taken TEXT,
            camera_model TEXT,
            lens TEXT,
            aperture TEXT,
            shutter_speed TEXT,
            iso TEXT,
            focal_length TEXT,
            gps TEXT,
            width INTEGER,
            height INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')
        
        conn.execute('''
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        ''')

def get_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def get_images(tag=None, search_query=None, page=0, per_page=50):
    """Get images with pagination"""
    conn = get_connection()
    query = "SELECT * FROM images"
    params = []
    
    if tag:
        query += " WHERE tags LIKE ?"
        params.append(f'%"{tag}"%')
    
    if search_query:
        if tag:
            query += " AND tags LIKE ?"
        else:
            query += " WHERE tags LIKE ?"
        params.append(f'%{search_query}%')
    
    # Order by date taken if available, otherwise by created_at
    query += " ORDER BY date_taken DESC NULLS LAST, created_at DESC"
    
    # Get total count for pagination
    count_query = "SELECT COUNT(*) FROM images"
    if tag or search_query:
        count_query += " WHERE " + query.split("WHERE", 1)[1].split("ORDER BY", 1)[0]
    
    total_count = conn.execute(count_query, params).fetchone()[0]
    
    # Add pagination
    query += " LIMIT ? OFFSET ?"
    params.extend([per_page, page * per_page])
    
    images = conn.execute(query, params).fetchall()
    conn.close()
    
    return images, total_count

def get_tags():
    conn = get_connection()
    tags = conn.execute(
        "SELECT * FROM tags ORDER BY count DESC, name"
    ).fetchall()
    conn.close()
    return tags

def get_popular_tags(limit=20):
    """Get most popular tags for the tag cloud"""
    conn = get_connection()
    tags = conn.execute(
        "SELECT name, count FROM tags ORDER BY count DESC LIMIT ?", 
        (limit,)
    ).fetchall()
    conn.close()
    return tags

def get_image_by_id(image_id):
    conn = get_connection()
    image = conn.execute("SELECT * FROM images WHERE id = ?", (image_id,)).fetchone()
    conn.close()
    return image

def update_image_tags(image_id, tags):
    conn = get_connection()
    
    # Get current tags
    cur_image = conn.execute("SELECT tags FROM images WHERE id = ?", (image_id,)).fetchone()
    if cur_image:
        current_tags = json.loads(cur_image['tags'])
        
        # Decrease count for tags that were removed
        for tag in current_tags:
            if tag not in tags:
                conn.execute("UPDATE tags SET count = count - 1 WHERE name = ?", (tag,))
    
    # Update the image
    conn.execute(
        "UPDATE images SET tags = ? WHERE id = ?",
        (json.dumps(tags), image_id)
    )
    
    # Add or update tags
    for tag in tags:
        try:
            # Try to insert new tag
            conn.execute("INSERT INTO tags (name, count) VALUES (?, 1)", (tag,))
        except sqlite3.IntegrityError:
            # Tag exists, update count if needed
            if cur_image and tag not in current_tags:
                conn.execute("UPDATE tags SET count = count + 1 WHERE name = ?", (tag,))
    
    conn.commit()
    conn.close()

def get_date_ranges():
    """Get available date ranges for filtering"""
    conn = get_connection()
    dates = conn.execute("SELECT date_taken FROM images WHERE date_taken IS NOT NULL ORDER BY date_taken").fetchall()
    conn.close()
    
    if not dates:
        return []
    
    # Group by year and month
    date_ranges = {}
    for date in dates:
        if date['date_taken']:
            try:
                date_obj = datetime.fromisoformat(date['date_taken'])
                year_month = date_obj.strftime("%Y-%m")
                if year_month not in date_ranges:
                    date_ranges[year_month] = {
                        "display": date_obj.strftime("%B %Y"),
                        "count": 0
                    }
                date_ranges[year_month]["count"] += 1
            except:
                pass
    
    # Sort by date (newest first)
    return sorted(
        [{"key": k, "display": v["display"], "count": v["count"]} for k, v in date_ranges.items()],
        key=lambda x: x["key"],
        reverse=True
    )

def is_import_running():
    """Check if an import process is running by checking the progress file."""
    if not os.path.exists(PROGRESS_FILE):
        return False
    
    try:
        with open(PROGRESS_FILE, 'r') as f:
            progress = json.load(f)
            
        # Consider the process still running if the status is not "completed"
        # and the last update was less than 5 minutes ago
        if progress.get('status') != 'completed':
            last_update = progress.get('timestamp', 0)
            current_time = time.time()
            if current_time - last_update < 300:  # 5 minutes
                return True
            else:
                # If more than 5 minutes have passed and status is not "completed",
                # the process probably crashed - update the file to mark as completed
                progress['status'] = 'completed'
                progress['timestamp'] = current_time
                with open(PROGRESS_FILE, 'w') as f:
                    json.dump(progress, f)
                return False
        
        return False
    except Exception as e:
        print(f"Error checking import status: {e}")
        return False

def get_import_progress():
    """Get the current import progress."""
    if not os.path.exists(PROGRESS_FILE):
        return None
    
    try:
        with open(PROGRESS_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return None

def start_import_process(source_dir, model_name, batch_size):
    """Start the import process as a background task."""
    # Create a clean progress file
    with open(PROGRESS_FILE, 'w') as f:
        json.dump({
            "total": 0,
            "current": 0, 
            "status": "starting",
            "timestamp": time.time()
        }, f)
    
    # Build command to run the import script
    cmd = [
        "python", "import_worker.py",
        "--source", source_dir,
        "--db", DATABASE,
        "--images-dir", UPLOAD_FOLDER,
        "--thumbnails-dir", THUMBNAIL_FOLDER,
        "--ollama-url", OLLAMA_URL,
        "--model", model_name,
        "--batch-size", str(batch_size)
    ]
    
    # Start the process
    subprocess.Popen(cmd, 
                     stdout=subprocess.PIPE, 
                     stderr=subprocess.PIPE, 
                     creationflags=subprocess.CREATE_NO_WINDOW)  # Windows specific
    
    return True

# Initialize database
init_db()

# Streamlit UI
st.title("AI Image Organizer")

# Add a progress indicator for ongoing imports in the sidebar
if is_import_running():
    with st.sidebar:
        st.subheader("Import Progress")
        progress = get_import_progress()
        if progress:
            current = progress.get('current', 0)
            total = progress.get('total', 1)  # Avoid division by zero
            percentage = min(100, int(current / total * 100)) if total > 0 else 0
            
            st.progress(current / total if total > 0 else 0)
            st.write(f"Processed: {current}/{total} images ({percentage}%)")
            
            if st.button("View Import Log"):
                if os.path.exists("import_log.txt"):
                    with open("import_log.txt", "r") as f:
                        log_content = f.read()
                    st.text_area("Log", log_content, height=300)
                else:
                    st.warning("Log file not found.")

# Check Ollama connection
ollama_connected = test_ollama_connection()
if not ollama_connected:
    st.sidebar.error(f"⚠️ Cannot connect to Ollama at {OLLAMA_URL}")

# Model selection in sidebar
available_models = ["llava:13b", "llava"]
selected_model = st.sidebar.selectbox("Select Model", available_models, index=0)

# Replace dropdown with proper button navigation
st.sidebar.subheader("Navigation")

# Define the navigation menu with icons
nav_options = [
    {"name": "Home", "icon": "🏠", "tooltip": "Browse photo gallery"},
    {"name": "Import Images", "icon": "📥", "tooltip": "Import new images"},
    {"name": "Tags", "icon": "🏷️", "tooltip": "Browse by tags"},
    {"name": "Find Duplicates", "icon": "🔍", "tooltip": "Find duplicate images"}
]

# Initialize page state if not present
if 'current_page' not in st.session_state:
    st.session_state.current_page = "Home"

# Create the navigation buttons
for option in nav_options:
    # Create a row for each navigation item 
    col1, col2 = st.sidebar.columns([1, 4])
    
    with col1:
        st.write(option["icon"])
    
    with col2:
        if st.button(
            option["name"], 
            key=f"nav_{option['name']}",
            help=option["tooltip"],
            use_container_width=True,
            type="primary" if st.session_state.current_page == option["name"] else "secondary"
        ):
            st.session_state.current_page = option["name"]
            # Reset page number when changing pages
            st.session_state.page_num = 0
            st.rerun()

# Use the selected page from session state instead of dropdown
page = st.session_state.current_page

# Add a separator
st.sidebar.markdown("---")

# Initialize pagination state if needed
if 'page_num' not in st.session_state:
    st.session_state.page_num = 0

if 'images_per_page' not in st.session_state:
    st.session_state.images_per_page = 60

# Create a tag cloud in the sidebar
with st.sidebar:
    st.subheader("Popular Tags")
    popular_tags = get_popular_tags(limit=25)
    if popular_tags:
        # Calculate tag sizes based on frequency
        max_count = max(tag['count'] for tag in popular_tags)
        min_count = min(tag['count'] for tag in popular_tags)
        
        # Create columns for tag cloud
        tag_cols = st.columns(3)
        for i, tag in enumerate(popular_tags):
            # Calculate size (1-5 scale)
            if max_count == min_count:
                size = 3
            else:
                size = 1 + int(4 * (tag['count'] - min_count) / (max_count - min_count))
            
            # Convert size to CSS font size
            font_size = 12 + (size * 2)
            
            with tag_cols[i % 3]:
                if st.button(
                    tag['name'], 
                    key=f"tag_btn_{tag['name']}",
                    use_container_width=True,
                    help=f"{tag['count']} images"
                ):
                    st.session_state.selected_tag = tag['name']
                    st.session_state.page_num = 0
                    st.rerun()

if st.session_state.current_page == "Home":
    st.header("Photo Gallery")
    
    # Search box
    search_query = st.text_input("Search images by tags", key="search_box")
    
    # Get selected tag from session state
    selected_tag = st.session_state.get('selected_tag', None)
    
    # Show selected tag as filter
    if selected_tag:
        st.info(f"Filtering by tag: {selected_tag}")
        if st.button("Clear Filter"):
            del st.session_state.selected_tag
            st.rerun()
    
    # Get images with pagination
    images, total_count = get_images(
        tag=selected_tag, 
        search_query=search_query,
        page=st.session_state.page_num,
        per_page=st.session_state.images_per_page
    )
    
    # Calculate total pages
    total_pages = math.ceil(total_count / st.session_state.images_per_page)
    
    if not images:
        st.info("No images found. Start by importing some images.")
    else:
        # Group images by date taken
        date_groups = {}
        for img in images:
            date_taken = img['date_taken'] if img['date_taken'] else "Unknown Date"
            
            # For known dates, group by day
            if date_taken != "Unknown Date":
                try:
                    date_obj = datetime.fromisoformat(date_taken)
                    date_key = date_obj.strftime("%Y-%m-%d")
                    friendly_date = date_obj.strftime("%B %d, %Y")
                except ValueError:
                    date_key = "Unknown"
                    friendly_date = "Unknown Date"
            else:
                date_key = "Unknown"
                friendly_date = "Unknown Date"
            
            if date_key not in date_groups:
                date_groups[date_key] = {"display_date": friendly_date, "images": []}
            
            date_groups[date_key]["images"].append(img)
        
        # Display each date group
        for date_key in sorted(date_groups.keys(), reverse=True):
            group = date_groups[date_key]
            
            st.subheader(group["display_date"])
            
            # Display image grid for this date - 4 images per row
            cols = st.columns(4)
            for i, img in enumerate(group["images"]):
                with cols[i % 4]:
                    try:
                        # Create clickable image with hover info
                        tags = json.loads(img['tags']) if img['tags'] else []
                        tag_str = ", ".join(tags[:3]) + ("..." if len(tags) > 3 else "")
                        
                        # Create a container for the image card
                        with st.container():
                            # Show image
                            st.image(
                                os.path.join(THUMBNAIL_FOLDER, img['thumbnail_path']),
                                use_container_width=True
                            )
                            
                            # Show some tag pills
                            if tags:
                                st.markdown(f"<div style='font-size:0.8em; color: #888;'>{tag_str}</div>", unsafe_allow_html=True)
                            
                            # Add a view button
                            if st.button("View", key=f"view_{img['id']}"):
                                st.session_state.selected_image = img['id']
                                st.rerun()
                            
                    except Exception as e:
                        st.error(f"Error displaying image: {e}")
        
        # Add pagination controls
        st.write("")  # Add some space
        cols = st.columns([1, 3, 1])
        
        with cols[0]:
            if st.session_state.page_num > 0:
                if st.button("← Previous"):
                    st.session_state.page_num -= 1
                    st.rerun()
        
        with cols[1]:
            st.write(f"Page {st.session_state.page_num + 1} of {total_pages} ({total_count} images)")
        
        with cols[2]:
            if st.session_state.page_num < total_pages - 1:
                if st.button("Next →"):
                    st.session_state.page_num += 1
                    st.rerun()

elif st.session_state.current_page == "Import Images":
    st.header("Import Images")
    
    source_dir = st.text_input("Directory Path", "D:\\OneDrive\\Pictures")
    batch_size = st.slider("Batch Size", min_value=10, max_value=100, value=20, 
                          help="Number of images to process at once")
    
    # Check if import is already running
    import_running = is_import_running()
    
    if import_running:
        progress = get_import_progress()
        col1, col2 = st.columns([3, 1])
        
        with col1:
            st.warning("An import process is already running!")
        
        with col2:
            if st.button("Reset Status", help="Use this if no import is actually running"):
                # Reset the progress file
                if os.path.exists(PROGRESS_FILE):
                    os.remove(PROGRESS_FILE)
                st.success("Import status reset!")
                st.rerun()
        
        if progress:
            current = progress.get('current', 0)
            total = progress.get('total', 1)
            percentage = min(100, int(current / total * 100)) if total > 0 else 0
            
            st.progress(current / total if total > 0 else 0)
            st.write(f"Processed: {current}/{total} images ({percentage}%)")
            
            if st.button("View Log"):
                if os.path.exists("import_log.txt"):
                    with open("import_log.txt", "r") as f:
                        log_content = f.read()
                    st.text_area("Log", log_content, height=300)
                else:
                    st.warning("Log file not found.")
    else:
        if st.button("Start Import"):
            if not ollama_connected:
                st.error("Cannot connect to Ollama. Please check the connection and try again.")
            elif os.path.isdir(source_dir):
                start_import_process(source_dir, selected_model, batch_size)
                st.success(f"Import process started in the background! You can navigate to other pages and the import will continue.")
                st.info("Check the sidebar for import progress.")
                st.rerun()  # Refresh to show progress
            else:
                st.error(f"Directory not found: {source_dir}")

elif st.session_state.current_page == "Tags":
    st.header("Browse by Tags")
    
    tags = get_tags()
    
    if not tags:
        st.info("No tags found. Import some images first.")
    else:
        # Show tags in a more usable format
        st.subheader(f"All Tags ({len(tags)})")
        
        # Create a tag cloud
        max_count = max(tag['count'] for tag in tags)
        min_count = min(tag['count'] for tag in tags)
        
        # Create a multi-column layout for tags
        num_cols = 5
        cols = st.columns(num_cols)
        
        for i, tag in enumerate(tags):
            # Calculate size (1-5 scale)
            if max_count == min_count:
                size = 3
            else:
                size = 1 + int(4 * (tag['count'] - min_count) / (max_count - min_count))
            
            # Convert size to CSS font size
            font_size = 14 + (size * 2)
            
            with cols[i % num_cols]:
                tag_btn = st.button(
                    f"{tag['name']} ({tag['count']})",
                    key=f"tag_btn_{tag['id']}",
                    use_container_width=True
                )
                if tag_btn:
                    st.session_state.selected_tag = tag['name']
                    st.session_state.current_page = "Home"
                    st.rerun()

elif st.session_state.current_page == "Find Duplicates":
    st.header("Find Duplicate Images")
    
    st.warning("This feature uses the database to find duplicates in already imported images.")
    
    # Get all images from the database
    conn = get_connection()
    all_hashes = conn.execute("SELECT hash, original_path, filename FROM images").fetchall()
    conn.close()
    
    # Group by hash
    hash_groups = {}
    for row in all_hashes:
        hash_val = row['hash']
        if hash_val not in hash_groups:
            hash_groups[hash_val] = []
        hash_groups[hash_val].append((row['original_path'], row['filename']))
    
    # Find duplicates (hashes with more than one file)
    duplicates = {h: files for h, files in hash_groups.items() if len(files) > 1}
    
    if not duplicates:
        st.success("No duplicate images found in the database.")
    else:
        st.warning(f"Found {len(duplicates)} sets of duplicate images in the database.")
        
        for i, (hash_val, files) in enumerate(list(duplicates.items())[:20]):  # Show first 20 duplicates
            st.write(f"Duplicate set {i+1} (Hash: {hash_val}):")
            
            # Display all files with this hash
            dup_cols = st.columns(len(files))
            for j, (original_path, filename) in enumerate(files):
                with dup_cols[j]:
                    st.write(f"File {j+1}")
                    try:
                        st.image(os.path.join(UPLOAD_FOLDER, filename), use_container_width=True)
                        st.caption(os.path.basename(original_path))
                    except Exception as e:
                        st.error(f"Error displaying image: {e}")
            
            st.markdown("---")

# Handle image detail view
if 'selected_image' in st.session_state:
    image = get_image_by_id(st.session_state.selected_image)
    
    if image:
        st.header(f"Image Details")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            try:
                st.image(
                    os.path.join(UPLOAD_FOLDER, image['filename']), 
                    use_container_width=True
                )
                # Add file operation buttons
                button_col1, button_col2 = st.columns(2)
                with button_col1:
                    if st.button("Open Original File", key="open_original"):
                        image_path = os.path.join(UPLOAD_FOLDER, image['filename'])
                        if os.path.exists(image_path):
                            if os.name == 'nt':  # Windows
                                os.startfile(image_path)
                            else:  # macOS or Linux
                                subprocess.run(['xdg-open', image_path])
                
                with button_col2:
                    if st.button("Show in Folder", key="show_folder"):
                        image_path = os.path.join(UPLOAD_FOLDER, image['filename'])
                        if os.path.exists(image_path):
                            if os.name == 'nt':  # Windows
                                subprocess.run(['explorer', '/select,', os.path.normpath(image_path)])
                            else:  # macOS or Linux
                                subprocess.run(['xdg-open', os.path.dirname(image_path)])
        
            except Exception as e:
                st.error(f"Error displaying image: {e}")
        
        with col2:
            st.subheader("Information")
            
            # Image metadata
            if image['date_taken']:
                try:
                    date_obj = datetime.fromisoformat(image['date_taken'])
                    st.write(f"**Date:** {date_obj.strftime('%B %d, %Y %H:%M')}")
                except:
                    st.write(f"**Date:** {image['date_taken']}")
            
            if image['camera_model']:
                st.write(f"**Camera:** {image['camera_model']}")
                
            # Technical details in a single row
            tech_details = []
            if image['focal_length']: tech_details.append(image['focal_length'])
            if image['aperture']: tech_details.append(image['aperture'])
            if image['shutter_speed']: tech_details.append(image['shutter_speed'])
            if image['iso']: tech_details.append(image['iso'])
            
            if tech_details:
                st.write(f"**Settings:** {' | '.join(tech_details)}")
            
            if image['width'] and image['height']:
                st.write(f"**Resolution:** {image['width']} × {image['height']}")
            
            st.write(f"**Original Path:** {image['original_path']}")
            st.write(f"**Added:** {image['created_at']}")
            
            # Tags
            st.subheader("Tags")
            current_tags = json.loads(image['tags']) if image['tags'] else []
            all_tags = [tag['name'] for tag in get_tags()]
            
            # Allow editing existing tags
            selected_tags = st.multiselect(
                "Select tags",
                options=sorted(list(set(all_tags + current_tags))),
                default=current_tags
            )
            
            # Allow adding new tags
            new_tag = st.text_input("Add new tag")
            if st.button("Add"):
                if new_tag and new_tag not in selected_tags:
                    selected_tags.append(new_tag)
            
            if st.button("Save Changes"):
                update_image_tags(
                    image['id'],
                    selected_tags
                )
                st.success("Changes saved!")
        
        if st.button("Back to Gallery"):
            del st.session_state.selected_image
            st.rerun()