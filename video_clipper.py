import sys
import vlc
import os
import random
import string
import datetime
from PyQt5.QtWidgets import (QApplication, QWidget, QPushButton, QVBoxLayout, QHBoxLayout, QScrollArea,
                             QFileDialog, QSlider, QLineEdit, QFrame, QSizePolicy, QLabel, QComboBox, QMessageBox)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPalette, QColor, QFont
from moviepy.video.io.ffmpeg_tools import ffmpeg_extract_subclip
from urllib.parse import urlparse, unquote

def format_time(milliseconds):
    """ Convert milliseconds to h:m:s format """
    seconds = int(milliseconds // 1000)
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    seconds = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

class TimeRow(QWidget):
    def __init__(self, video_player, parent):
        super().__init__()
        self.video_player = video_player
        self.parent = parent
        self.layout = QHBoxLayout()
        self.setLayout(self.layout)

        self.start_time = QLineEdit()
        self.layout.addWidget(self.start_time)

        self.end_time = QLineEdit()
        self.layout.addWidget(self.end_time)

        self.dropdown_label = QLabel("Class:")  # Label for the dropdown
        self.layout.addWidget(self.dropdown_label)

        self.class_dropdown = QComboBox()  # Dropdown box as the 4th component
        with open("classes.txt", "r") as file:
            classes = file.read().splitlines()
        self.class_dropdown.addItems(classes)
        self.layout.addWidget(self.class_dropdown)

        self.cut_button = QPushButton("CUT")
        self.cut_button.clicked.connect(self.cut_and_update_counts)
        self.layout.addWidget(self.cut_button)

        self.go_button = QPushButton("GO")
        self.go_button.clicked.connect(self.go_to_start_time)
        self.layout.addWidget(self.go_button)

    def cut_and_update_counts(self):
        self.cut_clip()
        self.video_player.update_class_counts()

    def go_to_start_time(self):
        time_str = self.start_time.text()
        if time_str:
            hours, minutes, seconds = map(int, time_str.split(':'))
            milliseconds = (hours * 3600 + minutes * 60 + seconds) * 1000
            self.video_player.player.set_time(milliseconds)
            self.video_player.playbackSlider.setValue(int(milliseconds))

    def cut_clip(self):
        start_time_str = self.start_time.text()
        end_time_str = self.end_time.text()
        selected_class = self.class_dropdown.currentText()
        self.video_player.trim_clip(start_time_str, end_time_str, selected_class, self)

class VideoPlayer(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Video Data Clipper")
        self.setGeometry(100, 100, 1200, 600)

        if not os.path.isfile("classes.txt"):
            QMessageBox.critical(self, "Error", "The 'classes.txt' file was not found.", QMessageBox.Ok, QMessageBox.Ok)
            sys.exit(1)

        main_layout = QHBoxLayout()
        self.setLayout(main_layout)

        self.is_slider_adjusted = False

        left_layout = QVBoxLayout()
        main_layout.addLayout(left_layout)

        self.vlc_instance = vlc.Instance()
        self.player = self.vlc_instance.media_player_new()

        self.video_frame = QFrame()
        self.video_frame.setPalette(QPalette(QColor(0, 0, 0)))
        self.video_frame.setAutoFillBackground(True)
        self.video_frame.setMinimumSize(640, 480)
        left_layout.addWidget(self.video_frame)

        self.playbackSlider = QSlider(Qt.Horizontal)
        self.playbackSlider.setMaximum(1000)
        self.playbackSlider.sliderMoved.connect(self.set_position)
        left_layout.addWidget(self.playbackSlider)

        self.timestamp_label = QLabel("00:00:00")
        self.timestamp_label.setFont(QFont("Arial", 14))
        left_layout.addWidget(self.timestamp_label)

        self.class_counts_label = QLabel("Class Counts: Loading...")
        self.class_counts_label.setFont(QFont("Arial", 12))
        left_layout.addWidget(self.class_counts_label)

        self.saved_video_label = QLabel("")
        self.saved_video_label.setFont(QFont("Arial", 12, QFont.Bold))
        left_layout.addWidget(self.saved_video_label)

        right_layout = QVBoxLayout()
        main_layout.addLayout(right_layout)

        control_layout = QHBoxLayout()
        right_layout.addLayout(control_layout)

        self.rewindButton = QPushButton('-5')
        self.rewindButton.clicked.connect(lambda: self.skip_seconds(-5000))
        control_layout.addWidget(self.rewindButton)

        self.rewind2Button = QPushButton('-2')
        self.rewind2Button.clicked.connect(lambda: self.skip_seconds(-2000))
        control_layout.addWidget(self.rewind2Button)

        self.playButton = QPushButton('Play')
        self.playButton.clicked.connect(self.toggle_playback)
        self.playButton.setFixedWidth(80)
        control_layout.addWidget(self.playButton)

        self.skip2Button = QPushButton('+2')
        self.skip2Button.clicked.connect(lambda: self.skip_seconds(2000))
        control_layout.addWidget(self.skip2Button)

        self.skipButton = QPushButton('+5')
        self.skipButton.clicked.connect(lambda: self.skip_seconds(5000))
        control_layout.addWidget(self.skipButton)

        self.buttonA = QPushButton('A')
        self.buttonA.clicked.connect(self.add_row)
        control_layout.addWidget(self.buttonA)

        self.buttonB = QPushButton('B')
        self.buttonB.clicked.connect(self.set_end_time)
        control_layout.addWidget(self.buttonB)

        self.loadButton = QPushButton('Load Video')
        self.loadButton.clicked.connect(self.load_video)
        control_layout.addWidget(self.loadButton)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        right_layout.addWidget(self.scroll_area)

        self.container_widget = QWidget()
        self.timestamp_layout = QVBoxLayout(self.container_widget)
        self.scroll_area.setWidget(self.container_widget)

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_ui)
        self.timer.start()

        self.rows = []
        self.trimmed_clip_counter = 0

        self.counter_label = QLabel("Trimmed Clips: 0")
        self.counter_label.setFont(QFont("Arial", 12, QFont.Bold))
        right_layout.addWidget(self.counter_label)

        self.credit_label = QLabel("Developed by: Avishek Das")
        self.credit_label.setFont(QFont("Arial", 10))
        self.credit_label.setAlignment(Qt.AlignRight | Qt.AlignBottom)
        right_layout.addWidget(self.credit_label)

        self.update_class_counts()

    def log_trim_operation(self, start_time_str, end_time_str, class_name, source_video_name, output_filename):
        log_entry = f"{start_time_str}, {end_time_str}, {class_name}, {source_video_name}, {output_filename}\n"
        log_file_path = "trim_operations_log.csv"
        with open(log_file_path, "a") as log_file:
            log_file.write(log_entry)

    def skip_seconds(self, milliseconds):
        current_time = self.player.get_time()
        new_time = max(current_time + milliseconds, 0)
        self.player.set_time(new_time)

    def update_class_counts(self):
        class_counts, total_files = self.get_class_counts()
        display_text = "<b>Total Files: {}</b><br>".format(total_files)
        display_text += "<br>".join(["<b>{}</b>: {}".format(class_name, count) for class_name, count in class_counts.items()])
        self.class_counts_label.setText(display_text)

    @staticmethod
    def get_class_counts():
        counts = {}
        total_files = 0
        if os.path.exists("trimmed_clips"):
            for class_folder in os.listdir("trimmed_clips"):
                folder_path = os.path.join("trimmed_clips", class_folder)
                if os.path.isdir(folder_path):
                    file_count = len([f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))])
                    counts[class_folder] = file_count
                    total_files += file_count
        return counts, total_files

    def load_video(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Open Video", "", "Video Files (*.mp4 *.avi *.mkv)")
        if filename:
            media = self.vlc_instance.media_new(filename)
            self.player.set_media(media)
            self.playButton.setEnabled(True)
            if sys.platform.startswith('linux'):
                self.player.set_xwindow(self.video_frame.winId())
            elif sys.platform == "win32":
                self.player.set_hwnd(self.video_frame.winId())
            elif sys.platform == "darwin":
                self.player.set_nsobject(self.video_frame.winId())

    def toggle_playback(self):
        if self.player.is_playing():
            self.player.pause()
            self.playButton.setText("Play")
        else:
            if self.player.play() == -1:
                self.playButton.setText("Play")
                return
            self.player.play()
            self.playButton.setText("Pause")

    def set_position(self, position):
        if not self.is_slider_adjusted:
            self.player.set_position(position / 1000.0)

    def update_ui(self):
        if not self.is_slider_adjusted:
            media_pos = self.player.get_position() * 1000
            self.playbackSlider.setValue(int(media_pos))
        current_time_str = format_time(self.player.get_time())
        self.timestamp_label.setText(current_time_str)

    def add_row(self):
        timestamp = int(self.player.get_time())
        formatted_time = format_time(timestamp)
        new_row = TimeRow(self, self.container_widget)
        new_row.start_time.setText(formatted_time)
        self.timestamp_layout.addWidget(new_row)
        self.rows.append(new_row)

    def set_end_time(self):
        if self.rows:
            timestamp = int(self.player.get_time())
            formatted_time = format_time(timestamp)
            self.rows[-1].end_time.setText(formatted_time)

    def trim_clip(self, start_time_str, end_time_str, selected_class, row):
        try:
            start_time = self.parse_time(start_time_str)
            end_time = self.parse_time(end_time_str)

            if start_time is not None and end_time is not None and start_time < end_time:
                video_url = self.player.get_media().get_mrl()
                video_path = unquote(urlparse(video_url).path[1:])
                output_dir = os.path.join("trimmed_clips", selected_class)
                os.makedirs(output_dir, exist_ok=True)
                random_string = ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(10))
                imported_file_name = os.path.basename(video_path).split(".")[0]
                output_filename = os.path.join(output_dir, f"{imported_file_name}_{random_string}.mp4")

                start_time_sec = start_time.hour * 3600 + start_time.minute * 60 + start_time.second
                end_time_sec = end_time.hour * 3600 + end_time.minute * 60 + end_time.second +1
                ffmpeg_extract_subclip(video_path, start_time_sec, end_time_sec, targetname=output_filename)

                self.saved_video_label.setText(f"Trimmed video saved as: {output_filename}")

                self.timestamp_layout.removeWidget(row)
                row.deleteLater()
                self.rows.remove(row)

                self.trimmed_clip_counter += 1
                self.update_row_counter()

                # Log the trim operation
                self.log_trim_operation(start_time_str, end_time_str, selected_class, os.path.basename(video_path), output_filename)

            else:
                print("Invalid start or end time.")
        except Exception as e:
            print(f"Error while trimming: {str(e)}")

    def update_row_counter(self):
        self.counter_label.setText(f"Trimmed Clips: {self.trimmed_clip_counter}")

    def parse_time(self, time_str):
        try:
            return datetime.datetime.strptime(time_str, "%H:%M:%S").time()
        except ValueError:
            return None

def main():
    app = QApplication(sys.argv)
    player = VideoPlayer()
    player.show()
    sys.exit(app.exec_())

if __name__ == '__main__':
    main()
