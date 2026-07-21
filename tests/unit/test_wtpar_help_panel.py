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
        self.assertIn('Alpine', self.content)
        self.assertIn('x-data', self.content)

    def test_wired_to_proxy_list(self):
        self.assertIn("callJsonApi('help'", self.content)
        self.assertIn("action: 'list'", self.content)
        self.assertIn("action: 'get'", self.content)
        self.assertIn('x-for="s in surfaces"', self.content)
        self.assertIn('class="error"', self.content)

    def test_dynamic_template_exists(self):
        self.assertIn('class="surface-header"', self.content)
        self.assertIn('class="surface-content"', self.content)
        self.assertIn('x-text="s.title"', self.content)
        self.assertIn('x-show="openId === s.id" x-collapse', self.content)
        self.assertIn('x-text="step"', self.content)
        self.assertIn('prerequisites', self.content.lower())

if __name__ == '__main__':
    unittest.main()
