Thermal_Monitoring_System_v2/
│
├── .git/
├── .venv/
├── .vscode/
│   └── settings.json
│
├── app/
│   ├── __init__.py
│   └── launcher.py
│
├── camera/
│   ├── __init__.py
│   ├── discovery/
│   │   ├── __init__.py
│   │   └── camera_discovery.py
│   │
│   ├── manager/
│   │   ├── __init__.py
│   │   └── camera_manager.py
│   │
│   ├── workers/
│   │   ├── __init__.py
│   │   └── camera_worker.py
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   └── camera_model.py
│   │
│   ├── interfaces/
│   │   ├── __init__.py
│   │   └── camera_interface.py
│   │
│   └── services/
│       └── __init__.py
│
├── processing/
│   ├── __init__.py
│   ├── pipeline/
│   │   ├── __init__.py
│   │   └── processing_pipeline.py
│   │
│   ├── converters/
│   │   ├── __init__.py
│   │   └── temperature_converter.py
│   │
│   ├── overlays/
│   │   ├── __init__.py
│   │   └── overlay_renderer.py
│   │
│   ├── statistics/
│   │   ├── __init__.py
│   │   └── roi_statistics.py
│   │
│   └── models/
│       ├── __init__.py
│       └── frame_result.py
│
├── roi/
│   ├── __init__.py
│   └── roi_manager.py
│
├── alarms/
│   ├── __init__.py
│   └── alarm_engine.py
│
├── recorder/
│   ├── __init__.py
│   └── recorder_engine.py
│
├── calibration/
│
├── database/
│   ├── __init__.py
│   ├── database_manager.py
│   └── database_models.py
│
├── gui/
│   ├── __init__.py
│   ├── observer/
│   │   ├── __init__.py
│   │   └── observer_window.py
│   │
│   ├── calibration/
│   │   └── __init__.py
│   │
│   ├── widgets/
│   │   ├── __init__.py
│   │   ├── thermal_view.py
│   │   └── camera_tile.py
│   │
│   └── resources/
│
├── configuration/
│   ├── __init__.py
│   └── settings.py
|   |── config/
│       ├── application.yaml
│       ├── database.yaml
│       ├── cameras.yaml
│       └── logging.yaml
│
|---core/
|   ├── __init__.py
|   ├── system_manager.py
|   ├── application.py
|   ├── exceptions.py
|   ├── enums.py
|   └── constants.py
|
|
├── utilities/
│   ├── __init__.py
│   ├── logger.py
│   └── helpers.py
│
├── assets/
│   ├── icons/
│   │   └── .gitkeep
│   ├── images/
│   │   └── .gitkeep
│   ├── themes/
│   │   └── .gitkeep
│   └── fonts/
│       └── .gitkeep
│
├── docs/
├── tests/
├── logs/
├── scripts/
│
├── README.md
├── PROJECT_STATUS.md
├── CHANGELOG.md
├── LICENSE
├── requirements.txt
└── .gitignore