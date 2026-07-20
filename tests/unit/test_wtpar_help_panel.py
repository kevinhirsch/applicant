import unittest
import os

PROJECT_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '../..'))
HELP_HTML = os.path.join(PROJECT_ROOT, 'a0-applicant', 'webui', 'help.html')

class TestWtparHelpPanel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.assertTrue(os.path.isfile(HELP_HTML),
                       f'help.html not found at {HELP_HTML}')
        with open(HELP_HTML, 'r', encoding='utf-8') as f:
            cls.content = f.read()

    def test_has_title(self):
        self.assertIn('<h1>Help &amp; Instructions</h1>', self.content)
        self.assertIn('<title>Help \u2014 Applications</title>', self.content)

    def test_has_alpine_js(self):
        self.assertIn('alpinejs', self.content)
        self.assertIn('x-data', self.content)

    def test_all_listed_surfaces_present(self):
        surfaces = [
            'Today',
            'Digest',
            'Documents',
            'Campaigns',
            'Activity',
            'Chat',
            'Live session',
            'Health',
        ]
        for surface in surfaces:
            with self.subTest(surface=surface):
                self.assertIn(surface, self.content,
                              f'{surface} surface section missing from help.html')

    def test_surface_headers_and_content_blocks(self):
        headers = self.content.count('class="surface-header"')
        contents = self.content.count('class="surface-content"')
        self.assertGreaterEqual(headers, 8)
        self.assertEqual(headers, contents,
                         'Each surface must have exactly one header and one content block')

if __name__ == '__main__':
    unittest.main()
