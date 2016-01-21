"""
dataset.py
"""
from functools import total_ordering
from six import (
    iteritems,
    with_metaclass,
)

from zipline.pipeline.term import (
    Term,
    AssetExists,
    NotSpecified,
)
from zipline.utils.input_validation import ensure_dtype
from zipline.utils.numpy_utils import (
    bool_dtype,
    default_missing_value_for_dtype,
    NoDefaultMissingValue,
)
from zipline.utils.preprocess import preprocess


class Column(object):
    """
    An abstract column of data, not yet associated with a dataset.
    """

    @preprocess(dtype=ensure_dtype)
    def __init__(self, dtype, missing_value=NotSpecified):
        self.dtype = dtype
        self.missing_value = missing_value

    def bind(self, name):
        """
        Bind a `Column` object to its name.
        """
        return _BoundColumnDescr(
            dtype=self.dtype,
            missing_value=self.missing_value,
            name=name,
        )


class _BoundColumnDescr(object):
    """
    Intermediate class that sits on `DataSet` objects and returns memoized
    `BoundColumn` objects when requested.

    This exists so that subclasses of DataSets don't share columns with their
    parent classes.
    """
    def __init__(self, dtype, missing_value, name):
        # Validating and calculating default missing values here guarantees
        # that we fail quickly if the user passes an unsupporte dtype or fails
        # to provide a missing value for a dtype that requires one
        # (e.g. int64), but still enables us to provide an error message that
        # points to the name of the failing column.
        try:
            self.dtype, self.missing_value = Term.validate_dtype(
                termname="Column(name={name!r})".format(name=name),
                dtype=dtype,
                missing_value=missing_value,
            )
        except NoDefaultMissingValue:
            # Re-raise with a more specific message.
            raise NoDefaultMissingValue(
                "Failed to create Column with name {name!r} and"
                " dtype {dtype} because no missing_value was provided\n\n"
                "Columns with dtype {dtype} require a missing_value.\n"
                "Please pass missing_value to Column() or use a different"
                " dtype.".format(dtype=dtype, name=name)
            )
        self.name = name

    def __get__(self, instance, owner):
        """
        Produce a concrete BoundColumn object when accessed.

        We don't bind to datasets at class creation time so that subclasses of
        DataSets produce different BoundColumns.
        """
        return BoundColumn(
            dtype=self.dtype,
            missing_value=self.missing_value,
            dataset=owner,
            name=self.name,
        )


class BoundColumn(Term):
    """
    A Column of data that's been concretely bound to a particular dataset.
    """
    mask = AssetExists()
    extra_input_rows = 0
    inputs = ()

    def __new__(cls, dtype, missing_value, dataset, name):
        return super(BoundColumn, cls).__new__(
            cls,
            domain=dataset.domain,
            dtype=dtype,
            missing_value=missing_value,
            dataset=dataset,
            name=name,
        )

    def _init(self, dataset, name, *args, **kwargs):
        self._dataset = dataset
        self._name = name
        return super(BoundColumn, self)._init(*args, **kwargs)

    @classmethod
    def static_identity(cls, dataset, name, *args, **kwargs):
        return (
            super(BoundColumn, cls).static_identity(*args, **kwargs),
            dataset,
            name,
        )

    @property
    def dataset(self):
        return self._dataset

    @property
    def name(self):
        return self._name

    @property
    def qualname(self):
        """
        Fully qualified of this column.
        """
        return '.'.join([self.dataset.__name__, self.name])

    @property
    def latest(self):
        if self.dtype == bool_dtype:
            from zipline.pipeline.filters import Latest
        else:
            from zipline.pipeline.factors import Latest
        return Latest(
            inputs=(self,),
            dtype=self.dtype,
            missing_value=self.missing_value,
        )

    def __repr__(self):
        return "{qualname}::{dtype}".format(
            qualname=self.qualname,
            dtype=self.dtype.name,
        )

    def short_repr(self):
        return self.qualname


@total_ordering
class DataSetMeta(type):
    """
    Metaclass for DataSets

    Supplies name and dataset information to Column attributes.
    """

    def __new__(mcls, name, bases, dict_):
        newtype = super(DataSetMeta, mcls).__new__(mcls, name, bases, dict_)
        # collect all of the column names that we inherit from our parents
        column_names = set().union(
            *(getattr(base, '_column_names', ()) for base in bases)
        )
        for maybe_colname, maybe_column in iteritems(dict_):
            if isinstance(maybe_column, Column):
                # add column names defined on our class
                bound_column_descr = maybe_column.bind(maybe_colname)
                setattr(newtype, maybe_colname, bound_column_descr)
                column_names.add(maybe_colname)

        newtype._column_names = frozenset(column_names)
        return newtype

    @property
    def columns(self):
        return frozenset(
            getattr(self, colname) for colname in self._column_names
        )

    def __lt__(self, other):
        return id(self) < id(other)

    def __repr__(self):
        return '<DataSet: %r>' % self.__name__


class DataSet(with_metaclass(DataSetMeta, object)):
    domain = None
