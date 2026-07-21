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
        self.assertIn('Alpine.data', self.content)
        self.assertIn('x-data', self.content)

    def test_dynamic_rendering_via_template_x_for(self):
        self.assertIn('x-for="s in surfaces"', self.content)
        self.assertIn('x-text="s.title"', self.content)
        self.assertIn(':key="s.id"', self.content)

    def test_calls_list_and_get_via_callJsonApi(self):
        self.assertIn("callJsonApi('help', { action: 'list' })", self.content)
        self.assertIn("callJsonApi('help', { action: 'get', surface: surfaceId })", self.content)

    def test_has_loading_error_and_empty_states(self):
        self.assertIn('class="loading"', self.content)
        self.assertIn('Loading help content...', self.content)
        self.assertIn('class="error"', self.content)
        self.assertIn('class="empty"', self.content)
        self.assertIn('No help content available.', self.content)

    def test_has_prerequisites_display(self):
        self.assertIn('class="prereq"', self.content)
        self.assertIn('x-text="openContent.prerequisites"', self.content)

    def test_has_surface_header_and_content_classes_in_template(self):
        # The template defines surface-header and surface-content classes
        # that are rendered dynamically at runtime.
        self.assertIn('class="surface-header"', self.content)
        self.assertIn('class="surface-content"', self.content)


if __name__ == '__main__':
    unittest.main()
