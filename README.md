# AI Image Organizer

A Streamlit-based application for organizing and managing large image collections using AI-powered categorization. This tool helps you classify, deduplicate, and browse your images with an intelligent tagging system that automatically identifies image content.

<img width="1680" alt="Screenshot 2025-04-29 at 22 42 32" src="https://github.com/user-attachments/assets/1e94822f-0224-4d9f-bfec-30532cc36b17" />
<img width="1674" alt="Screenshot 2025-04-29 at 22 42 48" src="https://github.com/user-attachments/assets/6acd3e37-dbd0-400c-b614-89e277ae64b1" />

## Features

- **AI-Powered Image Categorization**: Automatically analyzes and tags images using local Ollama AI models
- **Infinite Scrolling**: Browse your entire collection with lazy loading (no pagination)
- **Intelligent Search**: Find images by description or category
- **Duplicate Detection**: Identify and manage duplicate images using hash-based comparison
- **Privacy-First**: All processing happens locally - your images never leave your computer
- **Custom Categories**: Add, edit, or remove categories as needed
- **Bulk Import**: Easily import large image collections with background processing
- **Responsive UI**: Clean, intuitive interface designed for easy navigation
- **Detailed Image Information**: View and edit descriptions, categories, and metadata

## Installation

### Prerequisites

- Python 3.8 or higher
- [Ollama](https://ollama.ai/) with a vision model installed (e.g., llava)

### Setup Instructions

1. Clone the repository:
```bash
git clone https://github.com/yourusername/ai-image-organizer.git
cd ai-image-organizer
```

2. Install required dependencies:
```bash
pip install -r requirements.txt
```

3. Install and run Ollama with a vision model:
```bash
# Follow installation instructions at https://ollama.ai/
ollama pull llava
```

## Usage

1. Start the application:
```bash
streamlit run app.py
```

2. Open your browser and navigate to `http://localhost:8501`

3. Use the navigation sidebar to:
   - Import images from directories
   - Browse your collection by category
   - Find duplicate images
   - Search for specific images

## Technologies Used

- **Streamlit**: Frontend framework
- **Ollama**: Local AI model for image analysis
- **SQLite**: Database storage
- **Pillow**: Image processing
- **Python**: Core language


## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

Hope this helps you organize your massive image collection! If you have any questions or suggestions, please open an issue on this repository.
