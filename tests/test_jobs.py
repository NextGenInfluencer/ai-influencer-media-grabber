import sys
import threading
import time
import unittest
import job_process

class JobTests(unittest.TestCase):
    def test_stop_terminates_silent_external_process(self):
        job_process.begin_job()
        timer = threading.Timer(0.3, job_process.cancel_all)
        timer.start()
        started = time.monotonic()
        try:
            with self.assertRaisesRegex(RuntimeError, 'Cancelled'):
                job_process.run([sys.executable, '-c', 'import time; time.sleep(30)'], capture_output=True)
            self.assertLess(time.monotonic() - started, 8)
        finally:
            timer.join()
            job_process.end_job()

    def test_nested_playlist_entries_are_normalized(self):
        result = list(job_process.media_entries({'_type': 'playlist', 'entries': [None, {'id': 'one'},
                      {'_type': 'multi_video', 'entries': [{'id': 'two'}]}]}))
        self.assertEqual([entry['id'] for entry in result], ['one', 'two'])
