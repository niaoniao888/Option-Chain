import gc
import os
import tempfile
import threading
import unittest
import weakref
from pathlib import Path
from unittest.mock import patch

from options_panel.runtime.collector_supervisor import CollectorSupervisor


class FakeLock:
    def __init__(self, _path):
        self.acquired = 0
        self.released = 0

    def acquire(self):
        self.acquired += 1

    def release(self):
        self.released += 1


class FakeThread:
    def __init__(self, *, start_error=False):
        self.alive = False
        self.start_error = start_error
        self.starts = 0
        self.joins = 0

    def start(self):
        self.starts += 1
        if self.start_error:
            raise RuntimeError("start failed")
        self.alive = True

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        self.joins += 1


class CollectorSupervisorTests(unittest.TestCase):
    def make(self, thread, stop, locks):
        def lock_factory(path):
            lock = FakeLock(path)
            locks.append(lock)
            return lock

        return CollectorSupervisor(
            make_thread=lambda: thread,
            signal_stop=stop,
            lock_path=Path("fixture.lock"),
            join_timeout=15,
            lock_factory=lock_factory,
        )

    def test_duplicate_start_and_normal_stop_are_idempotent(self):
        locks = []
        thread = FakeThread()
        supervisor = self.make(thread, lambda item: setattr(item, "alive", False), locks)
        self.assertTrue(supervisor.start())
        self.assertFalse(supervisor.start())
        self.assertEqual(thread.starts, 1)
        self.assertTrue(supervisor.stop())
        self.assertTrue(supervisor.stop())
        self.assertEqual(locks[0].released, 1)

    def test_factory_and_thread_start_failures_release_lock(self):
        for factory in (
            lambda: (_ for _ in ()).throw(ValueError("factory")),
            lambda: FakeThread(start_error=True),
        ):
            locks = []
            supervisor = CollectorSupervisor(
                make_thread=factory,
                signal_stop=lambda _thread: None,
                lock_path=Path("fixture.lock"),
                lock_factory=lambda path: locks.append(FakeLock(path)) or locks[-1],
            )
            with self.assertRaises(Exception):
                supervisor.start()
            self.assertEqual(locks[0].released, 1)
            self.assertIsNone(supervisor.thread)

    def test_timeout_holds_lock_and_late_stop_releases(self):
        locks = []
        thread = FakeThread()
        supervisor = self.make(thread, lambda _item: None, locks)
        supervisor.start()
        self.assertFalse(supervisor.stop())
        self.assertIs(supervisor.thread, thread)
        self.assertEqual(locks[0].released, 0)
        self.assertFalse(supervisor.start())
        thread.alive = False
        self.assertTrue(supervisor.stop())
        self.assertEqual(locks[0].released, 1)

    def test_stop_callback_error_holds_lock_until_thread_finishes(self):
        locks = []
        thread = FakeThread()
        supervisor = self.make(
            thread,
            lambda _item: (_ for _ in ()).throw(RuntimeError("stop failed")),
            locks,
        )
        supervisor.start()
        with self.assertRaises(RuntimeError):
            supervisor.stop()
        self.assertEqual(locks[0].released, 0)
        thread.alive = False
        self.assertTrue(supervisor.stop())
        self.assertEqual(locks[0].released, 1)

    def test_third_market_can_reuse_supervisor_without_runtime_subclass(self):
        locks = []
        thread = FakeThread()
        stopped = []
        supervisor = self.make(thread, lambda item: stopped.append(item), locks)
        supervisor.start()
        thread.alive = False
        supervisor.stop()
        self.assertEqual(stopped, [])
        self.assertEqual(locks[0].released, 1)

    def test_repeated_start_stop_does_not_accumulate_threads_or_locks(self):
        retained_before = CollectorSupervisor.retained_owner_count()
        locks = []
        threads = []

        def make_thread():
            thread = FakeThread()
            threads.append(thread)
            return thread

        supervisor = CollectorSupervisor(
            make_thread=make_thread,
            signal_stop=lambda item: setattr(item, "alive", False),
            lock_path=Path("fixture.lock"),
            lock_factory=lambda path: locks.append(FakeLock(path)) or locks[-1],
        )
        for _ in range(50):
            self.assertTrue(supervisor.start())
            self.assertTrue(supervisor.stop())
            self.assertIsNone(supervisor.thread)
            self.assertIsNone(supervisor.lock)
        self.assertEqual(len(threads), 50)
        self.assertEqual(len(locks), 50)
        self.assertTrue(all(lock.released == 1 for lock in locks))
        self.assertEqual(CollectorSupervisor.retained_owner_count(), retained_before)

    def test_timeout_owner_survives_gc_until_real_thread_finishes(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "collector.lock"
            first_stop = threading.Event()
            first_thread = threading.Thread(target=first_stop.wait, daemon=True)
            first = CollectorSupervisor(
                make_thread=lambda: first_thread,
                signal_stop=lambda _thread: None,
                lock_path=lock_path,
                join_timeout=0.01,
            )
            first.start()
            self.assertFalse(first.stop())
            retained = weakref.ref(first)
            del first
            gc.collect()
            self.assertIsNotNone(retained())

            second_stop = threading.Event()
            second = CollectorSupervisor(
                make_thread=lambda: threading.Thread(target=second_stop.wait, daemon=True),
                signal_stop=lambda _thread: second_stop.set(),
                lock_path=lock_path,
                join_timeout=1,
            )
            with self.assertRaises(RuntimeError):
                second.start()

            first_stop.set()
            first_thread.join(timeout=1)
            self.assertFalse(first_thread.is_alive())
            self.assertTrue(second.start())
            self.assertTrue(second.stop())
            gc.collect()
            self.assertIsNone(retained())

    def test_stop_error_owner_survives_gc_until_real_thread_finishes(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "collector.lock"
            old_stop = threading.Event()
            old_thread = threading.Thread(target=old_stop.wait, daemon=True)
            old = CollectorSupervisor(
                make_thread=lambda: old_thread,
                signal_stop=lambda _thread: (_ for _ in ()).throw(
                    RuntimeError("stop failed")
                ),
                lock_path=lock_path,
                join_timeout=0.01,
            )
            old.start()
            with self.assertRaises(RuntimeError):
                old.stop()
            retained = weakref.ref(old)
            del old
            gc.collect()
            self.assertIsNotNone(retained())

            new_stop = threading.Event()
            new = CollectorSupervisor(
                make_thread=lambda: threading.Thread(target=new_stop.wait, daemon=True),
                signal_stop=lambda _thread: new_stop.set(),
                lock_path=lock_path,
                join_timeout=1,
            )
            with self.assertRaises(RuntimeError):
                new.start()
            old_stop.set()
            old_thread.join(timeout=1)
            self.assertTrue(new.start())
            self.assertTrue(new.stop())
            gc.collect()
            self.assertIsNone(retained())

    def test_owner_key_uses_platform_case_normalization(self):
        with tempfile.TemporaryDirectory() as directory:
            upper = CollectorSupervisor(
                make_thread=lambda: FakeThread(),
                signal_stop=lambda _thread: None,
                lock_path=Path(directory) / "Collector.lock",
            )
            lower = CollectorSupervisor(
                make_thread=lambda: FakeThread(),
                signal_stop=lambda _thread: None,
                lock_path=Path(directory) / "collector.lock",
            )
            with patch(
                "options_panel.runtime.collector_supervisor.os.path.normcase",
                side_effect=lambda value: value,
            ):
                self.assertNotEqual(upper._owner_key, lower._owner_key)

    @unittest.skipUnless(os.name == "posix", "requires a case-sensitive POSIX lock test")
    def test_case_distinct_posix_locks_survive_gc_and_reap_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            directory_path = Path(directory)
            upper_path = directory_path / "Collector.lock"
            lower_path = directory_path / "collector.lock"
            upper_stop = threading.Event()
            lower_stop = threading.Event()
            upper_thread = threading.Thread(target=upper_stop.wait, daemon=True)
            lower_thread = threading.Thread(target=lower_stop.wait, daemon=True)
            upper = CollectorSupervisor(
                make_thread=lambda: upper_thread,
                signal_stop=lambda _thread: None,
                lock_path=upper_path,
                join_timeout=0.01,
            )
            lower = CollectorSupervisor(
                make_thread=lambda: lower_thread,
                signal_stop=lambda _thread: None,
                lock_path=lower_path,
                join_timeout=0.01,
            )
            upper.start()
            lower.start()
            self.assertFalse(upper.stop())
            self.assertFalse(lower.stop())
            upper_ref = weakref.ref(upper)
            lower_ref = weakref.ref(lower)
            del upper, lower
            gc.collect()
            self.assertIsNotNone(upper_ref())
            self.assertIsNotNone(lower_ref())

            upper_next_stop = threading.Event()
            lower_next_stop = threading.Event()
            upper_next = CollectorSupervisor(
                make_thread=lambda: threading.Thread(
                    target=upper_next_stop.wait, daemon=True
                ),
                signal_stop=lambda _thread: upper_next_stop.set(),
                lock_path=upper_path,
                join_timeout=1,
            )
            lower_next = CollectorSupervisor(
                make_thread=lambda: threading.Thread(
                    target=lower_next_stop.wait, daemon=True
                ),
                signal_stop=lambda _thread: lower_next_stop.set(),
                lock_path=lower_path,
                join_timeout=1,
            )
            with self.assertRaises(RuntimeError):
                upper_next.start()
            with self.assertRaises(RuntimeError):
                lower_next.start()

            upper_stop.set()
            upper_thread.join(timeout=1)
            self.assertTrue(upper_next.start())
            self.assertTrue(upper_next.stop())
            with self.assertRaises(RuntimeError):
                lower_next.start()

            lower_stop.set()
            lower_thread.join(timeout=1)
            self.assertTrue(lower_next.start())
            self.assertTrue(lower_next.stop())
            gc.collect()
            self.assertIsNone(upper_ref())
            self.assertIsNone(lower_ref())


if __name__ == "__main__":
    unittest.main()
