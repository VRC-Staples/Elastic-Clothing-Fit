import os as _os

# These deployment scripts require Blender and run through tools/deploy.py.
collect_ignore = [
    _os.path.join(_os.path.dirname(__file__), "test_deployment_install.py"),
    _os.path.join(_os.path.dirname(__file__), "test_deployment_phase1.py"),
    _os.path.join(_os.path.dirname(__file__), "test_deployment_phase2.py"),
    _os.path.join(_os.path.dirname(__file__), "test_deployment_uninstall.py"),
]
