# encoding: UTF-8

from __future__ import unicode_literals

from contextlib import contextmanager
import os
import shutil
import stat
import tempfile

try:
    from itertools import izip
except ImportError:
    # Python 3
    izip = zip

try:
    xrange
except NameError:
    # Python 3
    xrange = range

from nose.tools import (
    assert_equal,
    assert_greater_equal,
    assert_is_none,
    assert_is_not_none,
    assert_list_equal,
    assert_raises,
    nottest)

import plyvel
from plyvel import DB

TEST_DB_DIR = 'testdb/'


#
# Utilities
#

def tmp_dir(name):
    return tempfile.mkdtemp(prefix=name + '-', dir=TEST_DB_DIR)


@contextmanager
def tmp_db(name, create=True):
    dir_name = tmp_dir(name)
    if create:
        db = DB(dir_name, create_if_missing=True, error_if_exists=True)
        yield db
        del db
    else:
        yield dir_name
    shutil.rmtree(dir_name)


#
# Test setup and teardown
#

def setup():
    try:
        os.mkdir(TEST_DB_DIR)
    except OSError as exc:
        if exc.errno == 17:
            # Directory already exists; ignore
            pass
        else:
            raise


def teardown():
    try:
        os.rmdir(TEST_DB_DIR)
    except OSError as exc:
        if exc.errno == 39:
            # Directory not empty; some tests failed
            pass
        else:
            raise


#
# Actual tests
#

def test_version():
    v = plyvel.__leveldb_version__
    assert v.startswith('1.')


def test_open():
    with tmp_db('read_only_dir', create=False) as name:
        # Opening a DB in a read-only dir should not work
        os.chmod(name, stat.S_IRUSR | stat.S_IXUSR)
        with assert_raises(plyvel.IOError):
            DB(name)

    with tmp_db('úñîçøđê_name') as db:
        pass

    with tmp_db('no_create', create=False) as name:
        with assert_raises(plyvel.Error):
            DB(name, create_if_missing=False)

    with tmp_db('exists', create=False) as name:
        db = DB(name, create_if_missing=True)
        del db
        with assert_raises(plyvel.Error):
            DB(name, error_if_exists=True)

    with assert_raises(TypeError):
        DB(123)

    with assert_raises(TypeError):
        DB('invalid_option_types', write_buffer_size='invalid')

    with assert_raises(TypeError):
        DB('invalid_option_types', lru_cache_size='invalid')

    with assert_raises(ValueError):
        DB('invalid_compression', compression='invalid',
           create_if_missing=True)

    with tmp_db('no_compression', create=False) as name:
        DB(name, compression=None, create_if_missing=True)

    with tmp_db('many_options', create=False) as name:
        DB(name, create_if_missing=True, error_if_exists=False,
           paranoid_checks=True, write_buffer_size=16 * 1024 * 1024,
           max_open_files=512, lru_cache_size=64 * 1024 * 1024,
           block_size=2 * 1024, block_restart_interval=32,
           compression='snappy', bloom_filter_bits=10)


def test_put():
    with tmp_db('put') as db:
        db.put(b'foo', b'bar')
        db.put(b'foo', b'bar', sync=False)
        db.put(b'foo', b'bar', sync=True)

        for i in xrange(1000):
            key = ('key-%d' % i).encode('UTF-8')
            value = ('value-%d' % i).encode('UTF-8')
            db.put(key, value)

        assert_raises(TypeError, db.put, b'foo', 12)
        assert_raises(TypeError, db.put, 12, 'foo')


def test_get():
    with tmp_db('get') as db:
        key = b'the-key'
        value = b'the-value'
        assert_is_none(db.get(key))
        db.put(key, value)
        assert_equal(value, db.get(key))
        assert_equal(value, db.get(key, verify_checksums=True))
        assert_equal(value, db.get(key, verify_checksums=False))
        assert_equal(value, db.get(key, verify_checksums=None))
        assert_equal(value, db.get(key, fill_cache=True))
        assert_equal(value, db.get(key, fill_cache=False, verify_checksums=None))

        assert_is_none(db.get(b'key-that-does-not-exist'))
        assert_raises(TypeError, db.get, 1)
        assert_raises(TypeError, db.get, 'foo')
        assert_raises(TypeError, db.get, None)
        assert_raises(TypeError, db.get, b'foo', True)


def test_delete():
    with tmp_db('delete') as db:
        # Put and delete a key
        key = b'key-that-will-be-deleted'
        db.put(key, b'')
        assert_is_not_none(db.get(key))
        db.delete(key)
        assert_is_none(db.get(key))

        # The .delete() method also takes write options
        db.put(key, b'')
        db.delete(key, sync=True)


def test_null_bytes():
    with tmp_db('null_bytes') as db:
        key = b'key\x00\x01'
        value = b'\x00\x00\x01'
        db.put(key, value)
        assert_equal(value, db.get(key))
        db.delete(key)
        assert_is_none(db.get(key))


def test_write_batch():
    with tmp_db('write_batch') as db:
        # Prepare a batch with some data
        batch = db.write_batch()
        for i in xrange(1000):
            batch.put(('batch-key-%d' % i).encode('UTF-8'), b'value')

        # Delete a key that was also set in the same (pending) batch
        batch.delete(b'batch-key-2')

        # The DB should not have any data before the batch is written
        assert_is_none(db.get(b'batch-key-1'))

        # ...but it should have data afterwards
        batch.write()
        assert_is_not_none(db.get(b'batch-key-1'))
        assert_is_none(db.get(b'batch-key-2'))

        # Batches can be cleared
        batch = db.write_batch()
        batch.put(b'this-is-never-saved', b'')
        batch.clear()
        batch.write()
        assert_is_none(db.get(b'this-is-never-saved'))

        # Batches take write options
        batch = db.write_batch(sync=True)
        batch.put(b'batch-key-sync', b'')
        batch.write()


def test_write_batch_context_manager():
    with tmp_db('write_batch_context_manager') as db:
        key = b'batch-key'
        assert_is_none(db.get(key))
        with db.write_batch() as wb:
            wb.put(key, b'')
        assert_is_not_none(db.get(key))

        # Data should also be written when an exception is raised
        key = b'batch-key-exception'
        assert_is_none(db.get(key))
        with assert_raises(ValueError):
            with db.write_batch() as wb:
                wb.put(key, b'')
                raise ValueError()
        assert_is_not_none(db.get(key))


def test_write_batch_transaction():
    with tmp_db('write_batch_transaction') as db:
        with assert_raises(ValueError):
            with db.write_batch(transaction=True) as wb:
                wb.put(b'key', b'value')
                raise ValueError()

        assert_list_equal([], list(db.iterator()))


def test_iteration():
    with tmp_db('iteration') as db:
        entries = []
        for i in xrange(100):
            entry = (
                ('%03d' % i).encode('UTF-8'),
                ('%03d' % i).encode('UTF-8'))
            entries.append(entry)

        for k, v in entries:
            db.put(k, v)

        for entry, expected in izip(entries, db):
            assert_equal(entry, expected)


def test_iterator_return():
    with tmp_db('iteration') as db:
        db.put(b'key', b'value')

    for key, value in db:
        assert_equal(key, b'key')
        assert_equal(value, b'value')

    for key, value in db.iterator():
        assert_equal(key, b'key')
        assert_equal(value, b'value')

    for key in db.iterator(include_value=False):
        assert_equal(key, b'key')

    for value in db.iterator(include_key=False):
        assert_equal(value, b'value')

    for ret in db.iterator(include_key=False, include_value=False):
        assert_is_none(ret)


@nottest
def test_manual_iteration(db, iter_kwargs, expected_values):
    it = db.iterator(**iter_kwargs)
    first, second, third = expected_values

    assert_equal(first, next(it))
    assert_equal(second, next(it))
    assert_equal(third, next(it))
    with assert_raises(StopIteration):
        next(it)
    with assert_raises(StopIteration):
        # second time may not cause a segfault
        next(it)


@nottest
def test_iterator_single_step(db, iter_kwargs, expected_values):
    it = db.iterator(**iter_kwargs)
    first, second, third = expected_values

    assert_equal(first, next(it))
    assert_equal(first, it.prev())
    assert_equal(first, next(it))
    assert_equal(first, it.prev())
    with assert_raises(StopIteration):
        it.prev()
    assert_equal(first, next(it))
    assert_equal(second, next(it))
    assert_equal(third, next(it))
    with assert_raises(StopIteration):
        next(it)
    assert_equal(third, it.prev())
    assert_equal(second, it.prev())


@nottest
def test_iterator_extremes(db, iter_kwargs, expected_values):
    it = db.iterator(**iter_kwargs)
    first, second, third = expected_values
    is_forward = not iter_kwargs.get('reverse', False)

    # End of iterator
    if is_forward:
        it.seek_to_stop()
    else:
        it.seek_to_start()
    with assert_raises(StopIteration):
        next(it)
    assert_equal(third, it.prev())

    # Begin of iterator
    if is_forward:
        it.seek_to_start()
    else:
        it.seek_to_stop()
    with assert_raises(StopIteration):
        it.prev()
    assert_equal(first, next(it))


def test_forward_iteration():
    with tmp_db('forward_iteration') as db:
        db.put(b'1', b'1')
        db.put(b'2', b'2')
        db.put(b'3', b'3')

        expected_values = (b'1', b'2', b'3')
        iter_kwargs = dict(include_key=False)
        test_manual_iteration(db, iter_kwargs, expected_values)
        test_iterator_single_step(db, iter_kwargs, expected_values)
        test_iterator_extremes(db, iter_kwargs, expected_values)


def test_reverse_iteration():
    with tmp_db('reverse_iteration') as db:
        db.put(b'1', b'1')
        db.put(b'2', b'2')
        db.put(b'3', b'3')

        expected_values = (b'3', b'2', b'1')
        iter_kwargs = dict(reverse=True, include_key=False)
        test_manual_iteration(db, iter_kwargs, expected_values)
        test_iterator_single_step(db, iter_kwargs, expected_values)
        test_iterator_extremes(db, iter_kwargs, expected_values)


def test_range_iteration():
    with tmp_db('range_iteration') as db:
        db.put(b'1', b'1')
        db.put(b'2', b'2')
        db.put(b'3', b'3')
        db.put(b'4', b'4')
        db.put(b'5', b'5')

        assert_list_equal(
            [b'2', b'3', b'4', b'5'],
            list(db.iterator(start=b'2', include_value=False)))

        assert_list_equal(
            [b'1', b'2'],
            list(db.iterator(stop=b'3', include_value=False)))

        assert_list_equal(
            [b'1', b'2'],
            list(db.iterator(start=b'0', stop=b'3', include_value=False)))

        assert_list_equal(
            [],
            list(db.iterator(start=b'3', stop=b'0')))

        # Only start
        expected_values = (b'3', b'4', b'5')
        iter_kwargs = dict(start=b'3', include_key=False)
        test_manual_iteration(db, iter_kwargs, expected_values)
        test_iterator_single_step(db, iter_kwargs, expected_values)
        test_iterator_extremes(db, iter_kwargs, expected_values)

        # Only stop
        expected_values = (b'1', b'2', b'3')
        iter_kwargs = dict(stop=b'4', include_key=False)
        test_manual_iteration(db, iter_kwargs, expected_values)
        test_iterator_single_step(db, iter_kwargs, expected_values)
        test_iterator_extremes(db, iter_kwargs, expected_values)

        # Both start and stop
        expected_values = (b'2', b'3', b'4')
        iter_kwargs = dict(start=b'2', stop=b'5', include_key=False)
        test_manual_iteration(db, iter_kwargs, expected_values)
        test_iterator_single_step(db, iter_kwargs, expected_values)
        test_iterator_extremes(db, iter_kwargs, expected_values)


def test_reverse_range_iteration():
    with tmp_db('reverse_range_iteration') as db:
        db.put(b'1', b'1')
        db.put(b'2', b'2')
        db.put(b'3', b'3')
        db.put(b'4', b'4')
        db.put(b'5', b'5')

        assert_list_equal(
            [],
            list(db.iterator(start=b'3', stop=b'0', reverse=True)))

        # Only start
        expected_values = (b'5', b'4', b'3')
        iter_kwargs = dict(start=b'3', reverse=True, include_value=False)
        test_manual_iteration(db, iter_kwargs, expected_values)
        test_iterator_single_step(db, iter_kwargs, expected_values)
        test_iterator_extremes(db, iter_kwargs, expected_values)

        # Only stop
        expected_values = (b'3', b'2', b'1')
        iter_kwargs = dict(stop=b'4', reverse=True, include_value=False)
        test_manual_iteration(db, iter_kwargs, expected_values)
        test_iterator_single_step(db, iter_kwargs, expected_values)
        test_iterator_extremes(db, iter_kwargs, expected_values)

        # Both start and stop
        expected_values = (b'3', b'2', b'1')
        iter_kwargs = dict(start=b'1', stop=b'4', reverse=True, include_value=False)
        test_manual_iteration(db, iter_kwargs, expected_values)
        test_iterator_single_step(db, iter_kwargs, expected_values)
        test_iterator_extremes(db, iter_kwargs, expected_values)


def test_range_empty_database():
    with tmp_db('range_empty_database') as db:
        it = db.iterator()
        it.seek_to_start()  # no-op (don't crash)
        it.seek_to_stop()  # no-op (don't crash)

        it = db.iterator()
        with assert_raises(StopIteration):
            next(it)

        it = db.iterator()
        with assert_raises(StopIteration):
            it.prev()
        with assert_raises(StopIteration):
            next(it)


def test_iterator_single_entry():
    with tmp_db('iterator_single_entry') as db:
        key = b'key'
        value = b'value'
        db.put(key, value)

        it = db.iterator(include_value=False)
        assert_equal(key, next(it))
        assert_equal(key, it.prev())
        assert_equal(key, next(it))
        assert_equal(key, it.prev())
        with assert_raises(StopIteration):
            it.prev()
        assert_equal(key, next(it))
        with assert_raises(StopIteration):
            next(it)


def test_iterator_seeking():
    with tmp_db('iterator_seeking') as db:
        db.put(b'1', b'1')
        db.put(b'2', b'2')
        db.put(b'3', b'3')
        db.put(b'4', b'4')
        db.put(b'5', b'5')

        it = db.iterator(include_value=False)
        it.seek_to_start()
        with assert_raises(StopIteration):
            it.prev()
        assert_equal(b'1', next(it))
        it.seek_to_start()
        assert_equal(b'1', next(it))
        it.seek_to_stop()
        with assert_raises(StopIteration):
            next(it)
        assert_equal(b'5', it.prev())

        # Seek to a specific key
        it.seek(b'2')
        assert_equal(b'2', next(it))
        assert_equal(b'3', next(it))
        assert_list_equal([b'4', b'5'], list(it))
        it.seek(b'2')
        assert_equal(b'1', it.prev())

        # Seek to keys that sort between/before/after existing keys
        it.seek(b'123')
        assert_equal(b'2', next(it))
        it.seek(b'6')
        with assert_raises(StopIteration):
            next(it)
        it.seek(b'0')
        with assert_raises(StopIteration):
            it.prev()
        assert_equal(b'1', next(it))
        it.seek(b'4')
        it.seek(b'3')
        assert_equal(b'3', next(it))

        # Seek in a reverse iterator
        it = db.iterator(include_value=False, reverse=True)
        it.seek(b'6')
        assert_equal(b'5', next(it))
        assert_equal(b'4', next(it))
        it.seek(b'1')
        with assert_raises(StopIteration):
            next(it)
        assert_equal(b'1', it.prev())

        # Seek in iterator with start key
        it = db.iterator(start=b'2', include_value=False)
        assert_equal(b'2', next(it))
        it.seek(b'2')
        assert_equal(b'2', next(it))
        it.seek(b'0')
        assert_equal(b'2', next(it))
        it.seek_to_start()
        assert_equal(b'2', next(it))

        # Seek in iterator with stop key
        it = db.iterator(stop=b'3', include_value=False)
        assert_equal(b'1', next(it))
        it.seek(b'2')
        assert_equal(b'2', next(it))
        it.seek(b'5')
        with assert_raises(StopIteration):
            next(it)
        it.seek(b'5')
        assert_equal(b'2', it.prev())
        it.seek_to_stop()
        with assert_raises(StopIteration):
            next(it)
        it.seek_to_stop()
        assert_equal(b'2', it.prev())

        # Seek in iterator with both start and stop keys
        it = db.iterator(start=b'2', stop=b'5', include_value=False)
        it.seek(b'0')
        assert_equal(b'2', next(it))
        it.seek(b'5')
        with assert_raises(StopIteration):
            next(it)
        it.seek(b'5')
        assert_equal(b'4', it.prev())

        # Seek in reverse iterator with start and stop key
        it = db.iterator(
            reverse=True, start=b'2', stop=b'4', include_value=False)
        it.seek(b'5')
        assert_equal(b'3', next(it))
        it.seek(b'1')
        assert_equal(b'2', it.prev())
        it.seek_to_start()
        with assert_raises(StopIteration):
            next(it)
        it.seek_to_stop()
        assert_equal(b'3', next(it))


def test_snapshot():
    with tmp_db('snapshot') as db:
        db.put(b'a', b'a')
        db.put(b'b', b'b')

        # Snapshot should have existing values, but not changed values
        snapshot = db.snapshot()
        assert_equal(b'a', snapshot.get(b'a'))
        assert_list_equal(
            [b'a', b'b'],
            list(snapshot.iterator(include_value=False)))
        assert_is_none(snapshot.get(b'c'))
        db.delete(b'a')
        db.put(b'c', b'c')
        assert_is_none(snapshot.get(b'c'))
        assert_list_equal(
            [b'a', b'b'],
            list(snapshot.iterator(include_value=False)))

        # New snapshot should reflect latest state
        snapshot = db.snapshot()
        assert_equal(b'c', snapshot.get(b'c'))
        assert_list_equal(
            [b'b', b'c'],
            list(snapshot.iterator(include_value=False)))

        # Snapshots are directly iterable, just like DB
        for entry in snapshot:
            pass


def test_compaction():
    with tmp_db('compaction') as db:
        db.compact_range()
        db.compact_range(start=b'a', stop=b'b')
        db.compact_range(start=b'a')
        db.compact_range(stop=b'b')


def test_approximate_sizes():
    with tmp_db('approximate_sizes', create=False) as name:

        # Write some data to a fresh database
        db = DB(name, create_if_missing=True, error_if_exists=True)
        value = b'a' * 1000
        with db.write_batch() as wb:
            for i in xrange(1000):
                key = bytes(i) * 1000
                wb.put(key, value)

        # Compact the database, so that pending write logs are
        # (hopefully) flushed to sst files.
        db.compact_range()

        with assert_raises(TypeError):
            db.approximate_size(1, 2)

        with assert_raises(TypeError):
            db.approximate_sizes(None)

        with assert_raises(TypeError):
            db.approximate_sizes((1, 2))

        # Test single range
        assert_greater_equal(db.approximate_size(b'1', b'2'), 0)

        # Test multiple ranges
        assert_list_equal([], db.approximate_sizes())
        assert_greater_equal(db.approximate_sizes((b'1', b'2'))[0], 0)

        ranges = [
            (b'1', b'3'),
            (b'', b'\xff'),
        ]
        assert_equal(len(ranges), len(db.approximate_sizes(*ranges)))


def test_repair_db():
    dir_name = tmp_dir('repair')
    db = DB(dir_name, create_if_missing=True)
    db.put(b'foo', b'bar')
    del db
    plyvel.repair_db(dir_name)
    db = DB(dir_name)
    assert_equal(b'bar', db.get(b'foo'))
    del db
    shutil.rmtree(dir_name)


def test_destroy_db():
    dir_name = tmp_dir('destroy')
    db = DB(dir_name, create_if_missing=True)
    db.put(b'foo', b'bar')
    del db
    plyvel.destroy_db(dir_name)
    assert not os.path.lexists(dir_name)


def test_threading():
    from threading import Thread, current_thread

    with tmp_db('threading') as db:

        N_PUTS = 1000
        N_THREADS = 10

        def bulk_insert(db):
            name = current_thread().name
            v = name.encode('ascii') * 500
            for n in xrange(N_PUTS):
                rev = '{:x}'.format(n)[::-1]
                k = '{}: {}'.format(rev, name).encode('ascii')
                db.put(k, v)

        threads = []
        for n in xrange(N_THREADS):
            t = Thread(target=bulk_insert, kwargs=dict(db=db))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()


def test_invalid_comparator():

    with tmp_db('invalid_comparator', create=False) as name:

        with assert_raises(ValueError):
            DB(name, comparator=None, comparator_name=b'invalid')

        with assert_raises(TypeError):
            DB(name,
               comparator=lambda x, y: 1,
               comparator_name=12)

        with assert_raises(TypeError):
            DB(name,
               comparator=b'not-a-callable',
               comparator_name=b'invalid')


def test_comparator():
    def comparator(a, b):
        a = a.lower()
        b = b.lower()
        if a < b:
            return -1
        if a > b:
            return 1
        else:
            return 0

    comparator_name = b"CaseInsensitiveComparator"

    with tmp_db('comparator', create=False) as name:
        db = DB(name,
                create_if_missing=True,
                comparator=comparator,
                comparator_name=comparator_name)

        keys = [
            b'aaa',
            b'BBB',
            b'ccc',
        ]

        with db.write_batch() as wb:
            for key in keys:
                wb.put(key, b'')

        assert_list_equal(
            sorted(keys, key=lambda s: s.lower()),
            list(db.iterator(include_value=False)))