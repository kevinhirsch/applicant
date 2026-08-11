from __future__ import annotations

import dataclasses

import pytest

from applicant.ports.driven.font_install import FontInstallPort, FontStatus


@pytest.fixture(autouse=True)
def _no_cache() -> None:
    pass


class TestFontStatusConstruction:
    """FontStatus: construction and defaults."""

    @pytest.mark.unit
    def test_all_positional(self) -> None:
        fs = FontStatus("Lato", True, "docker")
        assert fs.name == "Lato"
        assert fs.installed is True
        assert fs.environment == "docker"

    @pytest.mark.unit
    def test_all_keyword(self) -> None:
        fs = FontStatus(name="Roboto", installed=False, environment="host")
        assert fs.name == "Roboto"
        assert fs.installed is False
        assert fs.environment == "host"


class TestFontStatusFrozen:
    """FontStatus: immutability."""

    @pytest.mark.unit
    def test_cannot_set_name(self) -> None:
        fs = FontStatus("Lato", True, "docker")
        with pytest.raises(dataclasses.FrozenInstanceError):
            fs.name = "Roboto"

    @pytest.mark.unit
    def test_cannot_set_installed(self) -> None:
        fs = FontStatus("Lato", True, "docker")
        with pytest.raises(dataclasses.FrozenInstanceError):
            fs.installed = False

    @pytest.mark.unit
    def test_cannot_set_environment(self) -> None:
        fs = FontStatus("Lato", True, "docker")
        with pytest.raises(dataclasses.FrozenInstanceError):
            fs.environment = "host"


class TestFontStatusHashability:
    """FontStatus: hashable and usable in sets/dicts."""

    @pytest.mark.unit
    def test_hash_returns_int(self) -> None:
        fs = FontStatus("Lato", True, "docker")
        h = hash(fs)
        assert isinstance(h, int)

    @pytest.mark.unit
    def test_can_be_added_to_set(self) -> None:
        fs1 = FontStatus("Lato", True, "docker")
        fs2 = FontStatus("Roboto", False, "host")
        s = {fs1, fs2}
        assert len(s) == 2

    @pytest.mark.unit
    def test_equal_instances_have_same_hash(self) -> None:
        fs1 = FontStatus("Lato", True, "docker")
        fs2 = FontStatus("Lato", True, "docker")
        assert hash(fs1) == hash(fs2)


class TestFontStatusEquality:
    """FontStatus: equality comparisons."""

    @pytest.mark.unit
    def test_equal_when_fields_match(self) -> None:
        fs1 = FontStatus("Lato", True, "docker")
        fs2 = FontStatus("Lato", True, "docker")
        assert fs1 == fs2
        assert not (fs1 != fs2)

    @pytest.mark.unit
    def test_not_equal_when_name_differs(self) -> None:
        fs1 = FontStatus("Lato", True, "docker")
        fs2 = FontStatus("Roboto", True, "docker")
        assert fs1 != fs2

    @pytest.mark.unit
    def test_not_equal_when_installed_differs(self) -> None:
        fs1 = FontStatus("Lato", True, "docker")
        fs2 = FontStatus("Lato", False, "docker")
        assert fs1 != fs2

    @pytest.mark.unit
    def test_not_equal_when_environment_differs(self) -> None:
        fs1 = FontStatus("Lato", True, "docker")
        fs2 = FontStatus("Lato", True, "host")
        assert fs1 != fs2


class TestFontStatusRepr:
    """FontStatus: string representation."""

    @pytest.mark.unit
    def test_repr_contains_name(self) -> None:
        fs = FontStatus("Lato", True, "docker")
        r = repr(fs)
        assert "FontStatus" in r
        assert "Lato" in r
        assert "docker" in r


class TestFontInstallPort:
    """FontInstallPort: protocol structural typing."""

    @pytest.mark.unit
    def test_issubclass_of_protocol(self) -> None:
        assert isinstance(FontInstallPort, type)

    @pytest.mark.unit
    def test_class_satisfying_protocol_is_runtime_checkable(self) -> None:
        class FakeInstaller:
            def detect_required_fonts(self, document_path: str) -> list[str]:
                return []

            def install_font(self, font_path: str, name: str) -> FontStatus:
                return FontStatus(name, True, "docker")

            def list_fonts(self) -> list[FontStatus]:
                return [FontStatus("Lato", True, "docker")]

        installer = FakeInstaller()
        assert isinstance(installer, FontInstallPort)

    @pytest.mark.unit
    def test_class_missing_method_not_checkable(self) -> None:
        class IncompleteInstaller:
            def detect_required_fonts(self, document_path: str) -> list[str]:
                return []

            def install_font(self, font_path: str, name: str) -> FontStatus:
                return FontStatus(name, True, "docker")

            # missing list_fonts

        installer = IncompleteInstaller()
        assert not isinstance(installer, FontInstallPort)

    @pytest.mark.unit
    def test_install_font_returns_fontstatus(self) -> None:
        class FakeInstaller:
            def detect_required_fonts(self, document_path: str) -> list[str]:
                return []

            def install_font(self, font_path: str, name: str) -> FontStatus:
                return FontStatus(name, True, "docker")

            def list_fonts(self) -> list[FontStatus]:
                return []

        installer = FakeInstaller()
        result = installer.install_font("/tmp/font.ttf", "Lato")
        assert isinstance(result, FontStatus)
        assert result.name == "Lato"
        assert result.installed is True
        assert result.environment == "docker"

