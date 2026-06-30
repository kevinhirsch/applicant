"""Tests for gallery integration (#296)."""

from applicant.adapters.storage.in_memory import InMemoryStorage
from applicant.application.services.gallery_service import GalleryService


class TestGalleryService:
    def test_list_screenshots_empty(self):
        storage = InMemoryStorage()
        svc = GalleryService(storage)
        assert svc.list_screenshots("c-1") == []

    def test_list_materials_empty(self):
        storage = InMemoryStorage()
        svc = GalleryService(storage)
        assert svc.list_materials("c-1") == []

    def test_health_returns_true(self):
        storage = InMemoryStorage()
        svc = GalleryService(storage)
        assert svc.health()["available"] is True
