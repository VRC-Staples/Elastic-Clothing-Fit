# Keep update attempts under one owner

One owner in `updater.py` binds each download to an immutable release snapshot, its cancellation state, and its verified archive.
Discovery can report another release without changing the digest for an active attempt or its installation handoff.
Blender callers retain property reads, redraw, and restart effects.
The owner stays in `updater.py` because tests can call production commands through controlled Blender services.

Registration starts a new lifetime.
Unregister retires that lifetime, rejects late worker results, and clears readiness.
Installation makes sure that the verified archive is still current before it launches Blender.
