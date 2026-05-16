# Personalized Quran Reciter

A web application built with Streamlit for voice cloning your own recitation of the Holy Quran. 
Leveraging Text-to-Speech (TTS) with XTTS v2, the app allows you to browse surahs, select ayahs, provide a short voice sample, and generate high-quality personalized recitations of the selected verses.

## Features

- 📖 **Quran Explorer**: Navigate through all 114 Surahs and select specific Ayahs.
- 🎤 **Voice Cloning**: Provide a short sample of your voice (WAV, MP3, M4A, FLAC, OGG) to generate customized recitations using the XTTS v2 model.
- 💾 **Session History & DB**: The app saves your past generated recitations using an SQLite database so you can browse, playback, or download them at any time.
- 🎵 **Audio Playback**: Listen to your generated Quran recitation directly in the browser.
- 📥 **Download**: Download your personalized audio files seamlessly.

## Installation

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **System Requirements**:
   - Python 3.8+
   - For audio conversion `ffmpeg` and `libsndfile1` might be necessary depending on your environment. Since this runs via Streamlit and involves heavy TTS, a GPU is recommended.

## Running the App

1. **Start the Streamlit app**:
   ```bash
   streamlit run quran_app.py
   ```

2. **Access in the Browser**: Navigate to the URL shown in the terminal (usually `http://localhost:8501`).

## How to Use

### 1. Browse the Quran
- On the left sidebar, select a **Surah** from the dropdown menu.
- Specify the starting and ending **Ayahs** you want to synthesize. The Arabic text will be fetched from `data/quran-simple.txt`.

### 2. Upload Your Voice Sample
- Upload a clear **10-30 seconds** voice recording without background noise.
- The app supports `.wav`, `.mp3`, `.m4a`, and other audio formats, converting them automatically to `.wav`.

### 3. Generate Recitation
- Click the **"🎙️ Generate Recitation"** button.
- Wait for the model (XTTS v2) to process and synthesize the audio. The first time the model runs, it may need to download the weights.

### 4. History and Playback
- Check the **"📚 Recent Recordings"** in the sidebar to view, playback, or delete past generations.
- A direct playback and download button will be provided upon successful synthesis in the main panel.

## Troubleshooting

- **"Quran data not loaded"**: The file `data/quran-simple.txt` must be present.
- **Model downloading takes too long**: Initial downloads of the XTTS v2 model can be quite large. Ensure stable internet.
- **Slow Generation**: For faster processing, running on a machine with a CUDA-supported GPU is highly recommended. Set `CUDA_VISIBLE_DEVICES` correctly if running into issues.

## Project Structure

```
├── quran_app.py           # Main Streamlit application UI
├── quran_manager.py       # Handles reading and retrieving Quran verses
├── voice_cloner.py        # Wrapper around XTTS v2 for Arabic voice cloning
├── database.py            # SQLite operations for recording history
├── requirements.txt       # Python dependencies
├── packages.txt           # System-level dependencies
├── data/quran-simple.txt  # Arabic text of the Quran
└── recordings/            # Output folder for generated audio files
```

## License

This project utilizes the TTS library which is licensed under the MIT License/CPML. Output audio use may be subject to the Coqui Public Model License.
