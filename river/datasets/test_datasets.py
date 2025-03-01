import importlib
import inspect
import itertools
from urllib import request

import pytest

from river import datasets

from . import base


def _iter_datasets():

    for variant in datasets.Insects.variants:
        yield datasets.Insects(variant=variant)

    for _, dataset in inspect.getmembers(
        importlib.import_module("river.datasets"), inspect.isclass
    ):
        if dataset.__class__.__name__ != "Insects":
            yield dataset()


@pytest.mark.parametrize(
    "dataset",
    [
        pytest.param(dataset, id=dataset.__class__.__name__)
        for dataset in _iter_datasets()
        if isinstance(dataset, base.RemoteDataset)
    ],
)
@pytest.mark.datasets
def test_remote_url(dataset):
    with request.urlopen(dataset.url) as r:
        assert r.status == 200


@pytest.mark.parametrize(
    "dataset",
    [
        pytest.param(dataset, id=dataset.__class__.__name__)
        for dataset in _iter_datasets()
        if isinstance(dataset, base.RemoteDataset)
    ],
)
@pytest.mark.datasets
def test_remote_size(dataset):
    if dataset.path.is_file():
        size = dataset.path.stat().st_size
    else:
        size = sum(f.stat().st_size for f in dataset.path.glob("**/*") if f.is_file())
    assert size == dataset.size


@pytest.mark.parametrize(
    "dataset",
    [
        pytest.param(dataset, id=dataset.__class__.__name__)
        for dataset in _iter_datasets()
        if not isinstance(dataset, base.SyntheticDataset)
    ],
)
@pytest.mark.datasets
def test_dimensions(dataset):
    n = 0
    for x, _ in dataset:
        if not dataset.sparse:
            assert len(x) == dataset.n_features
        n += 1
    assert n == dataset.n_samples


@pytest.mark.parametrize(
    "dataset",
    [pytest.param(dataset, id=dataset.__class__.__name__) for dataset in _iter_datasets()],
)
def test_repr(dataset):
    assert repr(dataset)


def _iter_synth_datasets():

    synth = importlib.import_module("river.datasets.synth")
    for name, dataset in inspect.getmembers(synth, inspect.isclass):
        # TODO: test the following synth datasets also
        if name in ("RandomRBF", "RandomRBFDrift", "RandomTree", "ConceptDriftStream"):
            continue
        yield dataset


@pytest.mark.parametrize(
    "dataset",
    [pytest.param(dataset(seed=42), id=dataset.__name__) for dataset in _iter_synth_datasets()],
)
def test_synth_idempotent(dataset):
    """Checks that a synthetic dataset produces identical results when seeded."""
    assert list(dataset.take(5)) == list(dataset.take(5))


@pytest.mark.parametrize(
    "dataset",
    [pytest.param(dataset(seed=None), id=dataset.__name__) for dataset in _iter_synth_datasets()],
)
def test_synth_non_idempotent(dataset):
    """Checks that a synthetic dataset produces different results when not seeded."""
    assert list(dataset.take(5)) != list(dataset.take(5))


@pytest.mark.parametrize(
    "dataset",
    [pytest.param(dataset(seed=42), id=dataset.__name__) for dataset in _iter_synth_datasets()],
)
def test_synth_pausable(dataset):
    stream = iter(dataset)
    s1 = itertools.islice(stream, 3)
    s2 = itertools.islice(stream, 2)
    assert list(dataset.take(5)) == list(itertools.chain(s1, s2))
