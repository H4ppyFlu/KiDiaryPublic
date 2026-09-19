# The evening scheduler runs as its own Compose service

The job that sends each parent their evening notification runs as a separate Docker Compose service, using the same image as the API with a different command — one image, two services.

The obvious alternative is APScheduler inside the FastAPI process, which is one less service to define. It was rejected because a scheduler inside a multi-worker API process fires its job once per worker: both parents would receive duplicate notifications, and the fix would be a lock or a permanent single-worker constraint. Splitting the service makes the bug structurally impossible instead of something to remember.

Do not merge this back into the API process to save a service.
