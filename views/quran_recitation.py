"""
Personalized Quran Reciter Application
Voice clone your own recitation of the Holy Quran
"""

import streamlit as st
import os
import tempfile
import uuid
from pathlib import Path
from datetime import datetime
import warnings

from quran_manager import QuranManager
from voice_cloner import QuranVoiceCloner, convert_audio_to_wav, validate_audio_file
from database import (
    save_recording, get_recordings_by_session, get_all_recordings,
    delete_recording, get_voice_hash, RECORDINGS_DIR
)

warnings.filterwarnings("ignore")


def get_session_id():
    """Get or create a session ID for the user."""
    if 'session_id' not in st.session_state:
        st.session_state.session_id = str(uuid.uuid4())[:8]
    return st.session_state.session_id


def init_quran_manager():
    """Initialize the Quran manager with cached data."""
    if 'quran' not in st.session_state:
        quran = QuranManager()
        quran_file = Path("data/quran-simple.txt")
        if quran_file.exists():
            quran.load_quran_file(str(quran_file))
        st.session_state.quran = quran
    return st.session_state.quran


def init_voice_cloner():
    """Initialize the voice cloner."""
    if 'cloner' not in st.session_state:
        st.session_state.cloner = QuranVoiceCloner()
    return st.session_state.cloner


def format_surah_option(surah_num: int, arabic_name: str, english_name: str, total_ayahs: int) -> str:
    """Format surah for dropdown display."""
    return f"{surah_num}. {english_name} ({arabic_name}) - {total_ayahs} Ayahs"


def main():
    # Initialize components
    quran = init_quran_manager()
    cloner = init_voice_cloner()
    session_id = get_session_id()

    # Header
    st.markdown('<h1 style="font-size:2.5rem; text-align:center;">🕌 Personalized Quran Reciter</h1>', unsafe_allow_html=True)
    st.markdown('<p style="font-size:2rem; text-align:center; direction:rtl;">بِسْمِ اللَّهِ الرَّحْمَـٰنِ الرَّحِيمِ</p>', unsafe_allow_html=True)

    # Check if Quran data is loaded
    if not quran.is_loaded():
        st.error("⚠️ Quran data not loaded. Please ensure 'data/quran-simple.txt' exists.")
        return

    # Sidebar
    with st.sidebar:
        st.markdown("### 📖 Navigation")

        # Surah selection
        surah_list = quran.get_surah_list()
        surah_options = {
            format_surah_option(num, ar, en, total): num
            for num, ar, en, total in surah_list
        }

        selected_surah_str = st.selectbox(
            "Select Surah:",
            options=list(surah_options.keys()),
            index=0
        )
        selected_surah = surah_options[selected_surah_str]

        # Get surah info
        arabic_name, english_name = quran.get_surah_name(selected_surah)
        total_ayahs = quran.get_total_ayahs(selected_surah)

        st.info(f"**{arabic_name}** — {english_name} | {total_ayahs} Ayahs")

        # Ayah range selection
        st.markdown("### 📍 Ayah Selection")

        col1, col2 = st.columns(2)
        with col1:
            ayah_start = st.number_input(
                "From Ayah:",
                min_value=1,
                max_value=total_ayahs,
                value=1
            )
        with col2:
            ayah_end = st.number_input(
                "To Ayah:",
                min_value=1,
                max_value=total_ayahs,
                value=min(ayah_start + 2, total_ayahs)
            )

        # Ensure valid range
        if ayah_end < ayah_start:
            ayah_end = ayah_start

        st.markdown("---")

        # Recording history
        st.markdown("### 📚 Recent Recordings")

        recordings = get_all_recordings(limit=10)
        if recordings:
            for rec in recordings[:5]:
                with st.expander(f"Surah {rec['surah_number']}:{rec['ayah_start']}-{rec['ayah_end']}"):
                    st.caption(f"Created: {rec['created_at'][:16]}")
                    if os.path.exists(rec['audio_file_path']):
                        st.audio(rec['audio_file_path'])
                        if st.button("🗑️ Delete", key=f"del_{rec['id']}"):
                            delete_recording(rec['id'])
                            st.rerun()
        else:
            st.info("No recordings yet. Generate your first recitation!")

    # Main content area
    col_main, col_voice = st.columns([2, 1])

    with col_main:
        st.markdown("### 📜 Selected Verses")

        # Display selected ayahs
        ayah_text = quran.get_ayah_range(selected_surah, ayah_start, ayah_end)

        if ayah_text:
            st.markdown(
                f'<div style="font-size:1.8rem; font-family: serif; direction:rtl; '
                f'text-align:right; line-height:2.5; background:#FFF8E7; '
                f'padding:1.5rem; border-radius:10px; border:2px solid #B8860B; '
                f'margin:1rem 0;">{ayah_text}</div>',
                unsafe_allow_html=True
            )
            ayah_count = ayah_end - ayah_start + 1
            st.info(f"📖 Displaying {ayah_count} ayah(s) from Surah {english_name}")
        else:
            st.warning("Selected ayahs not found in the database.")

    with col_voice:
        st.markdown("### 🎤 Voice Sample")

        uploaded_voice = st.file_uploader(
            "Upload your voice sample",
            type=['wav', 'mp3', 'm4a', 'flac', 'ogg'],
            help="Upload a clear voice recording (10-30 seconds recommended)"
        )

        voice_path = None

        if uploaded_voice:
            st.success(f"✅ {uploaded_voice.name}")

            with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{uploaded_voice.name.split(".")[-1]}') as tmp:
                tmp.write(uploaded_voice.getvalue())
                temp_voice_path = tmp.name

            if not uploaded_voice.name.lower().endswith('.wav'):
                with st.spinner("Converting to WAV..."):
                    voice_path = convert_audio_to_wav(temp_voice_path)
            else:
                voice_path = temp_voice_path

            if voice_path and validate_audio_file(voice_path):
                st.audio(uploaded_voice)
                st.session_state.voice_path = voice_path
                st.session_state.voice_hash = get_voice_hash(voice_path)
            else:
                st.error("❌ Invalid audio file")

        elif 'voice_path' in st.session_state and os.path.exists(st.session_state.voice_path):
            st.info("Using previously uploaded voice sample")
            voice_path = st.session_state.voice_path

    # Generate button
    st.markdown("---")

    generate_col1, generate_col2, generate_col3 = st.columns([1, 2, 1])

    with generate_col2:
        if st.button("🎙️ Generate Recitation", type="primary", use_container_width=True):
            if not ayah_text:
                st.error("No ayah text available to recite.")
                return

            if 'voice_path' not in st.session_state:
                st.error("Please upload a voice sample first.")
                return

            voice_path = st.session_state.voice_path

            if not os.path.exists(voice_path):
                st.error("Voice sample not found. Please re-upload.")
                return

            with st.spinner("🕌 Generating your personalized recitation... This may take a few minutes."):
                try:
                    os.makedirs(RECORDINGS_DIR, exist_ok=True)
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    output_filename = f"surah{selected_surah}_ayah{ayah_start}-{ayah_end}_{timestamp}.wav"
                    output_path = os.path.join(RECORDINGS_DIR, output_filename)

                    progress = st.progress(0, text="Loading XTTS v2 model...")

                    if not cloner.model_loaded:
                        cloner.load_model()

                    progress.progress(30, text="Generating audio with voice cloning...")

                    result = cloner.clone_voice(
                        text=ayah_text,
                        voice_sample_path=voice_path,
                        output_path=output_path,
                        language="ar"
                    )

                    progress.progress(90, text="Saving recording...")

                    if result and os.path.exists(result):
                        duration = cloner.get_audio_duration(result)
                        file_size = cloner.get_file_size(result)

                        recording_id = save_recording(
                            user_session_id=session_id,
                            surah_number=selected_surah,
                            surah_name=english_name,
                            ayah_start=ayah_start,
                            ayah_end=ayah_end,
                            voice_sample_hash=st.session_state.voice_hash,
                            audio_file_path=result,
                            duration_seconds=duration,
                            file_size_bytes=file_size
                        )

                        progress.progress(100, text="Complete!")
                        st.success("✅ Recitation generated successfully!")

                        st.markdown("### 🎵 Your Personalized Recitation")
                        st.audio(result, format='audio/wav')

                        with open(result, 'rb') as f:
                            st.download_button(
                                label="📥 Download Recitation",
                                data=f.read(),
                                file_name=output_filename,
                                mime="audio/wav"
                            )

                        st.info(f"📊 Duration: {duration:.1f}s | Size: {file_size/1024:.1f} KB")

                    else:
                        st.error("❌ Failed to generate audio. Please try again.")

                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")

    # Footer
    st.markdown("---")
    st.markdown(
        '<div style="text-align:center; color:#666; padding:1rem;">'
        '<p>🕌 Personalized Quran Reciter • Powered by XTTS v2</p>'
        '<p style="font-size:0.8rem;">Use responsibly and with respect for the Holy Quran</p>'
        '</div>',
        unsafe_allow_html=True
    )


if __name__ == "__main__":
    main()
