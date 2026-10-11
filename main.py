import sys
import os
import random
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, 
                               QFileDialog, QCheckBox, QDoubleSpinBox, QGroupBox,
                               QProgressBar, QMessageBox)
from PySide6.QtCore import Qt, QThread, Signal
from moviepy import VideoFileClip, concatenate_videoclips, AudioFileClip
from moviepy.audio.AudioClip import concatenate_audioclips
from moviepy.video.fx import FadeIn, FadeOut
from scenedetect import detect, ContentDetector

# --- Worker Thread for Video Processing ---
class VideoWorker(QThread):
    progress_update = Signal(str)
    finished_signal = Signal(str)
    error_signal = Signal(str)

    def __init__(self, folder_path, music_path, settings):
        super().__init__()
        self.folder_path = folder_path
        self.music_path = music_path
        self.settings = settings
        self.running = True

    def run(self):
        try:
            self.process_video()
        except Exception as e:
            self.error_signal.emit(str(e))

    def process_video(self):
        clips = []
        opened_videos = []
        final_video = None
        
        try:
            min_dur = self.settings['min_dur']
            max_dur = self.settings['max_dur']
            total_dur = self.settings['total_dur']
            fade_dur = self.settings['fade_dur']
            smart_mode = self.settings['smart_mode']
            
            valid_ext = ('.mp4', '.mov', '.avi', '.mkv')
            files = [f for f in os.listdir(self.folder_path) if f.lower().endswith(valid_ext)]
            
            if not files:
                self.error_signal.emit("No video files found in the folder.")
                return

            random.shuffle(files)
            
            current_duration = 0
            clips_list = []
            limit_duration = total_dur > 0
            
            self.progress_update.emit("Analyzing and cutting clips...")
            
            file_idx = 0
            while True:
                if not self.running: break
                
                if limit_duration:
                    if current_duration >= total_dur: break
                else:
                    if file_idx >= len(files): break

                if file_idx >= len(files):
                    random.shuffle(files)
                    file_idx = 0
                
                filename = files[file_idx]
                filepath = os.path.join(self.folder_path, filename)
                file_idx += 1
                
                try:
                    video = VideoFileClip(filepath)
                    opened_videos.append(video)
                    clip = None

                    if smart_mode:
                        self.progress_update.emit(f"Detecting scenes in {filename}...")
                        scenes = detect(filepath, ContentDetector(threshold=27.0))
                        valid_scenes = []
                        
                        for start, end in scenes:
                            s_dur = (end - start).get_seconds()
                            if min_dur <= s_dur <= max_dur:
                                valid_scenes.append((start.get_seconds(), end.get_seconds()))
                        
                        if valid_scenes:
                            s, e = random.choice(valid_scenes)
                            clip = video.subclipped(s, e)
                    
                    if clip is None:
                        target_dur = random.uniform(min_dur, max_dur)
                        actual_dur = min(target_dur, video.duration)
                        start = random.uniform(0, max(0, video.duration - actual_dur))
                        clip = video.subclipped(start, start + actual_dur)
                    
                    clips_list.append(clip)
                    current_duration += clip.duration
                    
                    status = f"Clips: {len(clips_list)} | Duration: {current_duration:.1f}s"
                    self.progress_update.emit(status)

                except Exception as e:
                    print(f"Skipping {filename}: {e}")
                    continue

            if not clips_list:
                self.error_signal.emit("No clips could be created.")
                return

            if fade_dur > 0:
                self.progress_update.emit("Applying transitions...")
                clips_list = [c.with_effects([FadeIn(fade_dur), FadeOut(fade_dur)]) for c in clips_list]

            self.progress_update.emit("Concatenating video...")
            final_video = concatenate_videoclips(clips_list, method="compose")

            if self.music_path and os.path.exists(self.music_path):
                self.progress_update.emit("Mixing audio...")
                final_video = self.add_background_music(final_video, self.music_path)

            output_path = os.path.join(self.folder_path, "montage_final.mp4")
            self.progress_update.emit("Rendering final file...")
            
            final_video.write_videofile(
                output_path, 
                fps=24, 
                codec='libx264', 
                audio_codec='aac',
                threads=4,
                logger=None
            )
            
            self.finished_signal.emit(output_path)

        finally:
            for c in clips_list: c.close()
            for v in opened_videos: v.close()
            if final_video: final_video.close()

    def add_background_music(self, video, music_path):
        audio = AudioFileClip(music_path)
        
        if video.duration > audio.duration:
            n_loops = int(video.duration / audio.duration) + 1
            audio_clips = [audio] * n_loops
            final_audio = concatenate_audioclips(audio_clips).subclipped(0, video.duration)
        else:
            final_audio = audio.subclipped(0, video.duration)

        return video.with_audio(final_audio)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pro Video Montage Maker")
        self.resize(600, 500)
        
        self.setStyleSheet("""
            QMainWindow { background-color: #2b2b2b; }
            QLabel { color: #ffffff; }
            QGroupBox { 
                color: #ffffff; 
                border: 1px solid #555; 
                border-radius: 5px; 
                margin-top: 10px; 
                padding-top: 10px; 
            }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
            QLineEdit, QDoubleSpinBox { 
                background-color: #3c3c3c; 
                color: #ffffff; 
                border: 1px solid #555; 
                padding: 5px; 
                border-radius: 3px; 
            }
            QPushButton { 
                background-color: #0d47a1; 
                color: white; 
                border-radius: 5px; 
                padding: 8px; 
                font-weight: bold; 
            }
            QPushButton:hover { background-color: #1565c0; }
            QPushButton:disabled { background-color: #555; }
            QProgressBar {
                border: 2px solid grey;
                border-radius: 5px;
                text-align: center;
                color: white;
            }
            QCheckBox { color: white; }
        """)

        self.worker = None
        self.setup_ui()

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(10)

        input_group = QGroupBox("Input Files")
        input_layout = QVBoxLayout(input_group)
        
        h_box = QHBoxLayout()
        h_box.addWidget(QLabel("Video Folder:"))
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Select folder containing videos...")
        h_box.addWidget(self.folder_edit)
        btn_folder = QPushButton("Browse")
        btn_folder.clicked.connect(self.browse_folder)
        h_box.addWidget(btn_folder)
        input_layout.addLayout(h_box)

        h_box2 = QHBoxLayout()
        h_box2.addWidget(QLabel("Background Music:"))
        self.music_edit = QLineEdit()
        self.music_edit.setPlaceholderText("Optional: Select MP3 or WAV...")
        h_box2.addWidget(self.music_edit)
        btn_music = QPushButton("Browse")
        btn_music.clicked.connect(self.browse_music)
        h_box2.addWidget(btn_music)
        input_layout.addLayout(h_box2)
        
        layout.addWidget(input_group)

        settings_group = QGroupBox("Settings")
        settings_layout = QVBoxLayout(settings_group)

        self.smart_check = QCheckBox("Smart Clipping (Scene Detection)")
        self.smart_check.setChecked(True)
        settings_layout.addWidget(self.smart_check)

        grid = QHBoxLayout()
        
        grid.addWidget(QLabel("Min Clip (s):"))
        self.min_spin = QDoubleSpinBox()
        self.min_spin.setRange(0.5, 60.0)
        self.min_spin.setValue(2.0)
        grid.addWidget(self.min_spin)

        grid.addWidget(QLabel("Max Clip (s):"))
        self.max_spin = QDoubleSpinBox()
        self.max_spin.setRange(0.5, 60.0)
        self.max_spin.setValue(6.0)
        grid.addWidget(self.max_spin)

        grid.addWidget(QLabel("Fade (s):"))
        self.fade_spin = QDoubleSpinBox()
        self.fade_spin.setRange(0.0, 5.0)
        self.fade_spin.setValue(0.5)
        grid.addWidget(self.fade_spin)

        settings_layout.addLayout(grid)

        h_total = QHBoxLayout()
        h_total.addWidget(QLabel("Total Duration (s):"))
        self.total_spin = QDoubleSpinBox()
        self.total_spin.setRange(0.0, 9999.0)
        self.total_spin.setValue(60.0)
        self.total_spin.setToolTip("Set to 0 to use ALL clips from the folder once.")
        h_total.addWidget(self.total_spin)
        h_total.addWidget(QLabel("(0 = Use All Clips)"))
        h_total.addStretch()
        settings_layout.addLayout(h_total)

        layout.addWidget(settings_group)

        self.btn_start = QPushButton("Generate Montage")
        self.btn_start.setStyleSheet("background-color: #2e7d32; font-size: 14px; padding: 10px;")
        self.btn_start.clicked.connect(self.start_processing)
        layout.addWidget(self.btn_start)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0) 
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("Ready")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

    def browse_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Select Video Folder")
        if d:
            self.folder_edit.setText(d)

    def browse_music(self):
        f, _ = QFileDialog.getOpenFileName(self, "Select Music File", "", "Audio Files (*.mp3 *.wav *.aac)")
        if f:
            self.music_edit.setText(f)

    def start_processing(self):
        folder = self.folder_edit.text()
        if not folder:
            QMessageBox.warning(self, "Error", "Please select a video folder.")
            return
        
        if self.min_spin.value() > self.max_spin.value():
            QMessageBox.warning(self, "Error", "Min clip length cannot be greater than Max.")
            return

        settings = {
            'min_dur': self.min_spin.value(),
            'max_dur': self.max_spin.value(),
            'total_dur': self.total_spin.value(),
            'fade_dur': self.fade_spin.value(),
            'smart_mode': self.smart_check.isChecked()
        }

        self.btn_start.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.status_label.setText("Starting worker thread...")

        self.worker = VideoWorker(folder, self.music_edit.text(), settings)
        self.worker.progress_update.connect(self.on_progress_update)
        self.worker.finished_signal.connect(self.on_finished)
        self.worker.error_signal.connect(self.on_error)
        self.worker.start()

    def on_progress_update(self, msg):
        self.status_label.setText(msg)

    def on_finished(self, path):
        self.progress_bar.setVisible(False)
        self.btn_start.setEnabled(True)
        self.status_label.setText("Finished!")
        QMessageBox.information(self, "Success", f"Video saved to:\n{path}")

    def on_error(self, msg):
        self.progress_bar.setVisible(False)
        self.btn_start.setEnabled(True)
        self.status_label.setText("Error")
        QMessageBox.critical(self, "Error", msg)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())