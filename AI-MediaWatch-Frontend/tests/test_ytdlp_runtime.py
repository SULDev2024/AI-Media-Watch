"""Offline regression tests for YouTube download setup."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from threading import Event

import yt_dlp
from aimw.collection import ytdlp


class DownloadSetupTests(unittest.TestCase):
    def test_cancellation_during_download_does_not_publish_media(self):
        from aimw.workers.cancellation import JobCancelled
        stopped = Event()
        class InterruptedDownload:
            def __init__(self, options):
                self.options = options
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def extract_info(self, url, download):
                Path(self.options['outtmpl'].replace('%(ext)s', 'mp4')).write_bytes(b'partial')
                stopped.set()
                self.options['progress_hooks'][0]({'status': 'downloading'})
                raise AssertionError('Cancelled download must not continue')
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(yt_dlp, 'YoutubeDL', InterruptedDownload), patch.object(ytdlp, '_ffmpeg_dir', return_value=None):
                with self.assertRaises(JobCancelled):
                    ytdlp.download('https://www.youtube.com/watch?v=example', Path(folder), cancel_event=stopped)
            self.assertEqual(list(Path(folder).glob('*.mp4')), [])

    def test_cancelled_job_does_not_start_a_download(self):
        from aimw.workers.cancellation import JobCancelled
        stopped = Event()
        stopped.set()
        with tempfile.TemporaryDirectory() as folder, patch.object(yt_dlp, 'YoutubeDL') as downloader:
            with self.assertRaises(JobCancelled):
                ytdlp.download('https://www.youtube.com/watch?v=example', Path(folder), cancel_event=stopped)
            downloader.assert_not_called()

    def test_runtime_and_completed_media(self):
        captured = {}

        class FakeYoutubeDL:
            def __init__(self, options):
                captured.update(options)

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download):
                if download is not True:
                    raise AssertionError('Expected a media download')
                Path(captured['outtmpl'].replace('%(ext)s', 'mp4')).write_bytes(b'media')
                return {'duration': 12, 'title': 'Example', 'width': 640, 'height': 360}

        with tempfile.TemporaryDirectory() as folder:
            with patch.object(yt_dlp, 'YoutubeDL', FakeYoutubeDL), patch.object(ytdlp, '_ffmpeg_dir', return_value=None):
                result = ytdlp.download('https://www.youtube.com/watch?v=example', Path(folder))
            self.assertIn('node', captured['js_runtimes'])
            self.assertIn('deno', captured['js_runtimes'])
            self.assertFalse(captured['no_warnings'])
            self.assertEqual(result.path.read_bytes(), b'media')
            self.assertEqual(result.title, 'Example')
            self.assertEqual(result.duration_s, 12)

    def test_unavailable_source_does_not_produce_media(self):
        class UnavailableYoutubeDL:
            def __init__(self, options):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def extract_info(self, url, download):
                raise yt_dlp.utils.DownloadError('This video is not available')

        with tempfile.TemporaryDirectory() as folder:
            with patch.object(yt_dlp, 'YoutubeDL', UnavailableYoutubeDL), patch.object(ytdlp, '_ffmpeg_dir', return_value=None):
                with self.assertRaisesRegex(yt_dlp.utils.DownloadError, 'not available'):
                    ytdlp.download('https://www.youtube.com/watch?v=example', Path(folder))
            self.assertEqual(list(Path(folder).glob('*.mp4')), [])


if __name__ == '__main__':
    unittest.main()
