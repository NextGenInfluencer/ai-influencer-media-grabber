"""Temporary, isolated UI smoke-test server; does not touch the user's library."""
from test_media_safety import MediaTests
from waitress import serve

if __name__ == '__main__':
    MediaTests.setUpClass()
    demo = MediaTests('test_edited_image_and_export')
    demo.setUp()
    demo.test_edited_image_and_export()
    print('Generated sample video:', MediaTests.source, flush=True)
    print('Preview: http://127.0.0.1:5081', flush=True)
    try:
        serve(MediaTests.app, host='127.0.0.1', port=5081, threads=8)
    finally:
        MediaTests.tearDownClass()
