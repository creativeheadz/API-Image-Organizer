import os
import sys
import hashlib
import shutil
import sqlite3
import json
import time
import requests
import base64
from PIL import Image, ExifTags
import argparse
import logging
import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("import_log.txt"),
        logging.StreamHandler()
    ]
)

def calculate_file_hash(file_path):
    """Calculate SHA-256 hash of a file."""
    try:
        with open(file_path, 'rb') as f:
            file_hash = hashlib.sha256()
            chunk = f.read(8192)
            while chunk:
                file_hash.update(chunk)
                chunk = f.read(8192)
        return file_hash.hexdigest()
    except Exception as e:
        logging.error(f"Error hashing {file_path}: {e}")
        return None

def create_thumbnail(image_path, thumbnail_path, size=(300, 300)):
    """Create a thumbnail of the specified image."""
    try:
        with Image.open(image_path) as img:
            img.thumbnail(size)
            img.save(thumbnail_path)
        return True
    except Exception as e:
        logging.error(f"Error creating thumbnail: {e}")
        return False

def extract_image_metadata(image_path):
    """Extract EXIF metadata from image."""
    metadata = {
        "date_taken": None,
        "camera_model": None,
        "lens": None,
        "aperture": None,
        "shutter_speed": None,
        "iso": None,
        "focal_length": None,
        "gps": None,
        "width": None,
        "height": None,
    }
    
    try:
        with Image.open(image_path) as img:
            metadata["width"], metadata["height"] = img.size
            
            if hasattr(img, '_getexif') and img._getexif():
                exif = {
                    ExifTags.TAGS[k]: v
                    for k, v in img._getexif().items()
                    if k in ExifTags.TAGS
                }
                
                # Extract date taken
                if "DateTimeOriginal" in exif:
                    date_str = exif["DateTimeOriginal"]
                    try:
                        # Convert EXIF date format to timestamp
                        date_taken = datetime.datetime.strptime(date_str, "%Y:%m:%d %H:%M:%S")
                        metadata["date_taken"] = date_taken.isoformat()
                    except ValueError:
                        pass
                
                # Extract camera info
                if "Make" in exif and "Model" in exif:
                    metadata["camera_model"] = f"{exif['Make']} {exif['Model']}".strip()
                elif "Model" in exif:
                    metadata["camera_model"] = exif["Model"]
                
                # Extract lens info
                if "LensModel" in exif:
                    metadata["lens"] = exif["LensModel"]
                
                # Extract other camera settings
                if "FNumber" in exif and exif["FNumber"] > 0:
                    metadata["aperture"] = f"f/{exif['FNumber']}"
                
                if "ExposureTime" in exif:
                    exp_time = exif["ExposureTime"]
                    if exp_time < 1:
                        metadata["shutter_speed"] = f"1/{int(1/exp_time)}s"
                    else:
                        metadata["shutter_speed"] = f"{exp_time}s"
                
                if "ISOSpeedRatings" in exif:
                    metadata["iso"] = f"ISO {exif['ISOSpeedRatings']}"
                
                if "FocalLength" in exif:
                    metadata["focal_length"] = f"{exif['FocalLength']}mm"
                
                # Extract GPS if available
                if "GPSInfo" in exif and 2 in exif["GPSInfo"] and 4 in exif["GPSInfo"]:
                    lat = exif["GPSInfo"][2]
                    lon = exif["GPSInfo"][4]
                    
                    lat_ref = exif["GPSInfo"][1]
                    lon_ref = exif["GPSInfo"][3]
                    
                    lat = lat[0] + lat[1]/60 + lat[2]/3600
                    lon = lon[0] + lon[1]/60 + lon[2]/3600
                    
                    if lat_ref == 'S': lat = -lat
                    if lon_ref == 'W': lon = -lon
                    
                    metadata["gps"] = f"{lat},{lon}"
    except Exception as e:
        logging.error(f"Error extracting metadata from {image_path}: {e}")
    
    return metadata

def classify_image_with_ollama(image_path, ollama_url, model_name, retries=2):
    """Use Ollama vision model to classify the image content with tags only."""
    try:
        # Read image and encode as base64
        with open(image_path, 'rb') as img_file:
            image_data = base64.b64encode(img_file.read()).decode('utf-8')
        
        # Simplified prompt focused ONLY on tags
        prompt = """
        Look at this image and provide ONLY 5-10 simple single-word tags.

        RULES:
        - Use ONLY single words (no phrases)
        - Include subject matter, colors, mood, setting, visual elements
        - DO NOT use explanations or descriptions
        - DO NOT number your tags
        - DO NOT include sentences
        - Each tag should be a single word
        - Separate tags with commas only

        Example good result: sunset, beach, ocean, rocks, silhouette, orange, peaceful, horizon, nature, coastal

        Your response should ONLY contain:
        TAGS: tag1, tag2, tag3, tag4, tag5, tag6, tag7, tag8, tag9, tag10
        """
        
        # Make request to Ollama
        response = requests.post(
            ollama_url,
            json={
                "model": model_name,
                "prompt": prompt,
                "images": [image_data],
                "stream": False
            },
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            response_text = result.get('response', '')
            
            # Parse tags - look specifically for the TAGS: prefix
            tags = []
            tags_start = response_text.find("TAGS:")
            
            if tags_start >= 0:
                tags_text = response_text[tags_start+5:].strip()
                tags = [tag.strip() for tag in tags_text.split(',') if tag.strip()]
            else:
                # If no TAGS: prefix, just try to parse comma-separated words
                tags = [tag.strip() for tag in response_text.split(',') if tag.strip()]
            
            # Filter out any non-single words or empty strings
            tags = [tag for tag in tags if tag and ' ' not in tag]
            
            # Ensure we have at least one tag
            if not tags:
                tags = ["uncategorized"]
            
            return tags
            
        else:
            if retries > 0:
                logging.warning(f"Retrying connection to Ollama... ({retries} attempts left)")
                time.sleep(2)
                return classify_image_with_ollama(image_path, ollama_url, model_name, retries-1)
                
            logging.error(f"Error from Ollama API: {response.text}")
            return ["uncategorized"]
    
    except requests.exceptions.RequestException as e:
        if retries > 0:
            logging.warning(f"Connection issue with Ollama, retrying... ({retries} attempts left)")
            time.sleep(2)
            return classify_image_with_ollama(image_path, ollama_url, model_name, retries-1)
            
        logging.error(f"Failed to connect to Ollama at {ollama_url}: {e}")
        return ["error"]
    except Exception as e:
        logging.error(f"Error classifying image: {e}")
        return ["error"]

def find_images_in_directory(source_dir):
    """Find all image files in a directory."""
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}
    image_files = []
    
    logging.info(f"Finding images in directory: {source_dir}")
    for root, _, files in os.walk(source_dir):
        for file in files:
            if os.path.splitext(file.lower())[1] in image_extensions:
                full_path = os.path.join(root, file)
                image_files.append(full_path)
    
    logging.info(f"Found {len(image_files)} images")
    return image_files

def update_progress(total, current, status="processing"):
    """Update progress file for UI to read."""
    with open("import_progress.json", "w") as f:
        json.dump({
            "total": total,
            "current": current,
            "status": status,
            "timestamp": time.time()
        }, f)

def process_images(source_dir, db_path, images_dir, thumbnails_dir, ollama_url, model_name, batch_size=20):
    """Main function to process images."""
    # Make sure directories exist
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(thumbnails_dir, exist_ok=True)
    
    # Find all images
    image_files = find_images_in_directory(source_dir)
    total_images = len(image_files)
    processed = 0
    skipped = 0
    
    update_progress(total_images, 0, "starting")
    
    # Connect to database
    conn = sqlite3.connect(db_path)
    
    # Update database schema if needed
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
    
    # Process images in batches
    for i in range(0, total_images, batch_size):
        batch = image_files[i:min(i+batch_size, total_images)]
        
        for original_path in batch:
            try:
                # Generate filename from hash
                file_hash = calculate_file_hash(original_path)
                if not file_hash:
                    logging.error(f"Could not hash file: {original_path}")
                    continue
                
                filename = os.path.basename(original_path)
                secure_name = f"{file_hash[:10]}_{filename}"
                
                # Check if already in database
                cursor = conn.cursor()
                cursor.execute("SELECT id FROM images WHERE hash = ?", (file_hash,))
                if cursor.fetchone() is not None:
                    logging.info(f"Skipping duplicate: {original_path}")
                    skipped += 1
                    processed += 1
                    update_progress(total_images, processed, "processing")
                    continue
                
                # Copy file and create thumbnail
                new_path = os.path.join(images_dir, secure_name)
                thumbnail_path = os.path.join(thumbnails_dir, secure_name)
                
                shutil.copy2(original_path, new_path)
                create_thumbnail(new_path, thumbnail_path)
                
                # Extract metadata
                metadata = extract_image_metadata(new_path)
                
                # Classify image (get tags)
                tags = classify_image_with_ollama(new_path, ollama_url, model_name)
                
                # Add to database with metadata
                cursor.execute(
                    """
                    INSERT INTO images 
                    (filename, original_path, hash, thumbnail_path, tags, 
                    date_taken, camera_model, lens, aperture, shutter_speed, 
                    iso, focal_length, gps, width, height) 
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        secure_name,
                        original_path,
                        file_hash,
                        os.path.basename(thumbnail_path),
                        json.dumps(tags),
                        metadata.get('date_taken'),
                        metadata.get('camera_model'),
                        metadata.get('lens'),
                        metadata.get('aperture'),
                        metadata.get('shutter_speed'),
                        metadata.get('iso'),
                        metadata.get('focal_length'),
                        metadata.get('gps'),
                        metadata.get('width'),
                        metadata.get('height')
                    )
                )
                
                # Add or update tags
                for tag in tags:
                    try:
                        # Try to insert new tag
                        cursor.execute("INSERT INTO tags (name, count) VALUES (?, 1)", (tag,))
                    except sqlite3.IntegrityError:
                        # Tag exists, update count
                        cursor.execute("UPDATE tags SET count = count + 1 WHERE name = ?", (tag,))
                
                conn.commit()
                processed += 1
                logging.info(f"Processed {processed}/{total_images}: {original_path}")
                
                # Update progress
                update_progress(total_images, processed, "processing")
                
            except Exception as e:
                logging.error(f"Error processing {original_path}: {e}")
                processed += 1
                update_progress(total_images, processed, "processing")
    
    # Finalize
    conn.close()
    update_progress(total_images, total_images, "completed")
    logging.info(f"Import completed. Processed: {processed}, Skipped: {skipped}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Import and process images")
    parser.add_argument("--source", required=True, help="Source directory with images")
    parser.add_argument("--db", required=True, help="Path to SQLite database")
    parser.add_argument("--images-dir", required=True, help="Directory to store images")
    parser.add_argument("--thumbnails-dir", required=True, help="Directory to store thumbnails")
    parser.add_argument("--ollama-url", required=True, help="URL to Ollama API")
    parser.add_argument("--model", default="llava:13b", help="Model name to use for classification")
    parser.add_argument("--batch-size", type=int, default=20, help="Batch size for processing")
    
    args = parser.parse_args()
    
    process_images(
        args.source,
        args.db,
        args.images_dir,
        args.thumbnails_dir,
        args.ollama_url,
        args.model,
        args.batch_size
    )