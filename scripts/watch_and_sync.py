"""
Auto-sync script that watches for changes to sample_data.json
and automatically updates vector embeddings.

Install watchdog first: pip install watchdog
"""
import os
import sys
import time
from pathlib import Path

# Disable ChromaDB telemetry to avoid errors
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
os.environ.setdefault("CHROMA_TELEMETRY_DISABLED", "1")

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    print("Error: watchdog package not found.")
    print("Install it with: pip install watchdog")
    sys.exit(1)

from app.ingestion_pipeline.vector_store import sync_vector_store


class DataFileChangeHandler(FileSystemEventHandler):
    """Handler for file system events."""
    
    def __init__(self, data_file_path: Path, project_root: Path):
        self.data_file_path = data_file_path
        self.project_root = project_root
        self.last_sync_time = 0
        self.cooldown_seconds = 5  # Prevent multiple syncs in quick succession
    
    def on_modified(self, event):
        """Called when a file is modified."""
        if event.is_directory:
            return
        
        # Check if the modified file is our data file
        if Path(event.src_path).resolve() == self.data_file_path.resolve():
            current_time = time.time()
            
            # Check cooldown to prevent multiple rapid syncs
            if current_time - self.last_sync_time < self.cooldown_seconds:
                return
            
            self.last_sync_time = current_time
            
            print("\n" + "=" * 60)
            print(f"📝 Detected change in {self.data_file_path.name}")
            print("=" * 60)
            print("Starting auto-sync...")
            
            try:
                sync_vector_store(
                    data_file=str(self.data_file_path),
                    collection_name="property_listings",
                    persist_directory=str(self.project_root / "chroma_db")
                )
                print("\n✅ Auto-sync complete! Vector embeddings updated.")
                print("Watching for more changes...\n")
                
            except Exception as e:
                print(f"\n❌ Error during auto-sync: {e}")
                import traceback
                traceback.print_exc()
                print("\nWatching for more changes...\n")


def main():
    """Start watching the data file for changes."""
    print("=" * 60)
    print("🔍 Auto-Sync Watcher for Property Listings")
    print("=" * 60)
    
    # Get project root and data file path
    project_root = Path(__file__).parent.parent
    data_file = project_root / "app" / "knowledge_base" / "sample_data.json"
    
    # Check if file exists
    if not data_file.exists():
        print(f"Error: File not found: {data_file}")
        print("Please ensure the sample_data.json file exists.")
        return
    
    print(f"📁 Watching file: {data_file}")
    print(f"📊 Vector store: {project_root / 'chroma_db'}")
    print("\nℹ️  Any changes to sample_data.json will automatically")
    print("   trigger a sync of the vector embeddings.")
    print("\nPress Ctrl+C to stop watching.\n")
    
    # Set up file system observer
    event_handler = DataFileChangeHandler(data_file, project_root)
    observer = Observer()
    observer.schedule(
        event_handler,
        path=str(data_file.parent),
        recursive=False
    )
    
    # Start watching
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n" + "=" * 60)
        print("🛑 Stopping watcher...")
        print("=" * 60)
        observer.stop()
    
    observer.join()
    print("Watcher stopped. Goodbye!")


if __name__ == "__main__":
    main()

