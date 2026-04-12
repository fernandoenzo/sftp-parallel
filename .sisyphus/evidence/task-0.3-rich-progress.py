#!/usr/bin/env python3
"""
Test: Rich progress bar with ThreadPoolExecutor
Verifies that Rich can update progress bars while concurrent tasks run.
"""
import subprocess
import time
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from concurrent.futures import ThreadPoolExecutor

def run_fake_upload(i):
    """Simulate upload work with sleep."""
    time.sleep(0.5)
    return i

def test_threadpool_progress():
    """Test Rich progress bar with thread pool."""
    print("=== Test 1: ThreadPoolExecutor with Rich Progress ===")
    
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        SpinnerColumn(),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    ) as progress:
        upload_task = progress.add_task("Uploading...", total=5)
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(run_fake_upload, i) for i in range(5)]
            completed = 0
            for future in futures:
                future.result()
                completed += 1
                progress.update(upload_task, completed=completed)
                print(f"  Completed: {completed}/5")

    print("Test 1 PASSED: ThreadPool progress bar worked\n")

def test_subprocess_popen():
    """Test Rich progress bar with actual subprocess.Popen."""
    print("=== Test 2: subprocess.Popen with Rich Progress ===")
    
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        SpinnerColumn(),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    ) as progress:
        task = progress.add_task("Running subprocesses...", total=3)
        
        for i in range(3):
            proc = subprocess.Popen(["sleep", "0.3"])
            proc.wait()
            progress.update(task, completed=i+1)
            print(f"  Subprocess {i+1}/3 completed")

    print("Test 2 PASSED: subprocess.Popen worked with Rich\n")

def test_concurrent_subprocesses():
    """Test Rich progress with multiple subprocesses running concurrently."""
    print("=== Test 3: Concurrent subprocesses with Rich Progress ===")
    
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        SpinnerColumn(),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
    ) as progress:
        task = progress.add_task("Concurrent uploads...", total=4)
        
        processes = []
        # Start 4 subprocesses
        for i in range(4):
            proc = subprocess.Popen(["sleep", "0.2"])
            processes.append(proc)
        
        # Wait for all and update progress
        completed = 0
        for proc in processes:
            proc.wait()
            completed += 1
            progress.update(task, completed=completed)
            print(f"  Concurrent subprocess {completed}/4 done")

    print("Test 3 PASSED: Concurrent subprocesses worked with Rich\n")

if __name__ == "__main__":
    print("Testing Rich progress bar with subprocess.Popen\n")
    print("=" * 60)
    
    test_threadpool_progress()
    test_subprocess_popen()
    test_concurrent_subprocesses()
    
    print("=" * 60)
    print("ALL TESTS PASSED!")
    print("Rich progress bars work correctly with subprocess.Popen")