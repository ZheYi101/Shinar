"""Qt's generated caches use one product directory without moving user stores."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QStandardPaths

from shinar.desktop.shell import identity, settings


@pytest.mark.parametrize("platform,organization", [("nt", ""), ("posix", "Shinar")])
def test_application_identity_preserves_brand_and_explicit_settings(
    monkeypatch, qt_app, platform, organization
):
    original_organization = qt_app.organizationName()
    namespaces = []
    monkeypatch.setattr(identity, "os", SimpleNamespace(name=platform))
    monkeypatch.setattr(settings, "QSettings", lambda *args: namespaces.append(args))
    try:
        identity.configure_application_identity(qt_app)
        assert qt_app.applicationName() == "Shinar"
        assert qt_app.applicationDisplayName() == "Shinar"
        assert qt_app.organizationName() == organization
        assert not qt_app.windowIcon().isNull()
        assert identity.WINDOWS_APP_ID == "Shinar.Desktop"
        settings.ProductSettings("Workspace")
        assert namespaces == [("Shinar", "Workspace"), ("LinguaLoop", "Workspace")]
    finally:
        qt_app.setOrganizationName(original_organization)


def test_windows_qt_cache_location_has_only_one_product_directory(qt_app):
    original_organization = qt_app.organizationName()
    try:
        identity.configure_application_identity(qt_app)
        cache = Path(QStandardPaths.writableLocation(QStandardPaths.CacheLocation))
        local_data = Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))
        if os.name == "nt":
            assert cache.parts[-2:] == ("Shinar", "cache")
            assert local_data.parts[-1:] == ("Shinar",)
            assert local_data.parent.name != "Shinar"
        else:
            assert cache.name == "Shinar"
    finally:
        qt_app.setOrganizationName(original_organization)
