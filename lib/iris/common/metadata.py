# Copyright Iris contributors
#
# This file is part of Iris and is released under the LGPL license.
# See COPYING and COPYING.LESSER in the root of the repository for full
# licensing details.

from abc import ABCMeta
from collections import namedtuple
from collections.abc import Iterable, Mapping
from functools import wraps
import re


__all__ = [
    "AncillaryVariableMetadata",
    "BaseMetadata",
    "CellMeasureMetadata",
    "CoordMetadata",
    "CubeMetadata",
    "MetadataManagerFactory",
]


# https://www.unidata.ucar.edu/software/netcdf/docs/netcdf_data_set_components.html#object_name
_TOKEN_PARSE = re.compile(r"""^[a-zA-Z0-9][\w\.\+\-@]*$""")


class _NamedTupleMeta(ABCMeta):
    """
    Meta-class to support the convenience of creating a namedtuple from
    names/members of the metadata class hierarchy.

    """

    def __new__(mcs, name, bases, namespace):
        token = "_members"
        names = []

        for base in bases:
            if hasattr(base, token):
                base_names = getattr(base, token)
                is_abstract = getattr(
                    base_names, "__isabstractmethod__", False
                )
                if not is_abstract:
                    if (not isinstance(base_names, Iterable)) or isinstance(
                        base_names, str
                    ):
                        base_names = (base_names,)
                    names.extend(base_names)

        if token in namespace and not getattr(
            namespace[token], "__isabstractmethod__", False
        ):
            namespace_names = namespace[token]

            if (not isinstance(namespace_names, Iterable)) or isinstance(
                namespace_names, str
            ):
                namespace_names = (namespace_names,)

            names.extend(namespace_names)

        if names:
            item = namedtuple(f"{name}Namedtuple", names)
            bases = list(bases)
            # Influence the appropriate MRO.
            bases.insert(0, item)
            bases = tuple(bases)

        return super().__new__(mcs, name, bases, namespace)


class BaseMetadata(metaclass=_NamedTupleMeta):
    """
    Container for common metadata.

    * This and the derived types are NamedTuples.
      They are immutable, and have "_fields" = list of tuple names.
      The names are signature properties of Iris data elements,
      e.g. 'long_name', 'units' etc.

    * each _DimensionalMetadata subclass defines a specific subclass of
      BaseMetadata for its signature type.
      It also defines public getters + setters for its extra signature fields.
      The universal ones are inherited from `~iris.common.mixin.CFVariableMixin`.

    * each _DimensionalMetadata instance has a "self._metadata_manager",
      creating by calling MetadataManagerFactory, passing its own specific
      signature subclass of BaseMetadata.

    """

    DEFAULT_NAME = "unknown"  # the fall-back name for metadata identity

    _members = (
        "standard_name",
        "long_name",
        "var_name",
        "units",
        "attributes",
    )

    __slots__ = ()

    @classmethod
    def token(cls, name):
        """
        Determine whether the provided name is a valid NetCDF name and thus
        safe to represent a single parsable token.

        Args:

        * name:
            The string name to verify

        Returns:
            The provided name if valid, otherwise None.

        """
        if name is not None:
            result = _TOKEN_PARSE.match(name)
            name = result if result is None else name
        return name

    def name(self, default=None, token=False):
        """
        Returns a string name representing the identity of the metadata.

        First it tries standard name, then it tries the long name, then
        the NetCDF variable name, before falling-back to a default value,
        which itself defaults to the string 'unknown'.

        Kwargs:

        * default:
            The fall-back string representing the default name. Defaults to
            the string 'unknown'.
        * token:
            If True, ensures that the name returned satisfies the criteria for
            the characters required by a valid NetCDF name. If it is not
            possible to return a valid name, then a ValueError exception is
            raised. Defaults to False.

        Returns:
            String.

        """

        def _check(item):
            return self.token(item) if token else item

        default = self.DEFAULT_NAME if default is None else default

        result = (
            _check(self.standard_name)
            or _check(self.long_name)
            or _check(self.var_name)
            or _check(default)
        )

        if token and result is None:
            emsg = "Cannot retrieve a valid name token from {!r}"
            raise ValueError(emsg.format(self))

        return result

    def __lt__(self, other):
        #
        # Support Python2 behaviour for a "<" operation involving a
        # "NoneType" operand. Require to at least implement this comparison
        # operator to support sorting of instances.
        #
        if not isinstance(other, self.__class__):
            return NotImplemented

        def _sort_key(item):
            keys = []
            for field in item._fields:
                value = getattr(item, field)
                keys.extend((value is not None, value))
            return tuple(keys)

        return _sort_key(self) < _sort_key(other)


class AncillaryVariableMetadata(BaseMetadata):
    """
    Metadata container for a :class:`~iris.coords.AncillaryVariableMetadata`.

    """

    __slots__ = ()


class CellMeasureMetadata(BaseMetadata):
    """
    Metadata container for a :class:`~iris.coords.CellMeasure`.

    """

    _members = "measure"

    __slots__ = ()


class CoordMetadata(BaseMetadata):
    """
    Metadata container for a :class:`~iris.coords.Coord`.

    """

    _members = ("coord_system", "climatological")

    __slots__ = ()


class CubeMetadata(BaseMetadata):
    """
    Metadata container for a :class:`~iris.cube.Cube`.

    """

    _members = "cell_methods"

    __slots__ = ()

    @wraps(BaseMetadata.name)
    def name(self, default=None, token=False):
        def _check(item):
            return self.token(item) if token else item

        default = self.DEFAULT_NAME if default is None else default

        # Defensive enforcement of attributes being a dictionary.
        if not isinstance(self.attributes, Mapping):
            try:
                self.attributes = dict()
            except AttributeError:
                emsg = "Invalid '{}.attributes' member, must be a mapping."
                raise AttributeError(emsg.format(self.__class__.__name__))

        result = (
            _check(self.standard_name)
            or _check(self.long_name)
            or _check(self.var_name)
            or _check(str(self.attributes.get("STASH", "")))
            or _check(default)
        )

        if token and result is None:
            emsg = "Cannot retrieve a valid name token from {!r}"
            raise ValueError(emsg.format(self))

        return result

    @property
    def _names(self):
        """
        A tuple containing the value of each name participating in the identity
        of a :class:`iris.cube.Cube`. This includes the standard name,
        long name, NetCDF variable name, and the STASH from the attributes
        dictionary.

        """
        standard_name = self.standard_name
        long_name = self.long_name
        var_name = self.var_name

        # Defensive enforcement of attributes being a dictionary.
        if not isinstance(self.attributes, Mapping):
            try:
                self.attributes = dict()
            except AttributeError:
                emsg = "Invalid '{}.attributes' member, must be a mapping."
                raise AttributeError(emsg.format(self.__class__.__name__))

        stash_name = self.attributes.get("STASH")
        if stash_name is not None:
            stash_name = str(stash_name)

        return (standard_name, long_name, var_name, stash_name)


def MetadataManagerFactory(cls, **kwargs):
    """
    A class instance factory function responsible for manufacturing
    metadata instances dynamically at runtime.

    The factory instances returned by the factory are capable of managing
    their metadata state, which can be proxied by the owning container.

    Args:

    * cls:
        A subclass of :class:`~iris.common.metadata.BaseMetadata`, defining
        the metadata to be managed.

    Kwargs:

    * kwargs:
        Initial values for the manufactured metadata instance. Unspecified
        fields will default to a value of 'None'.

    """

    def __init__(self, cls, **kwargs):
        # Restrict to only dealing with appropriate metadata classes.
        if not issubclass(cls, BaseMetadata):
            emsg = "Require a subclass of {!r}, got {!r}."
            raise TypeError(emsg.format(BaseMetadata.__name__, cls))

        #: The metadata class to be manufactured by this factory.
        self.cls = cls

        # Initialise the metadata class fields in the instance.
        for field in self.fields:
            setattr(self, field, None)

        # Populate with provided kwargs, which have already been verified
        # by the factory.
        for field, value in kwargs.items():
            setattr(self, field, value)

    def __eq__(self, other):
        if not hasattr(other, "cls"):
            return NotImplemented
        match = self.cls is other.cls
        if match:
            match = self.values == other.values
        return match

    def __getstate__(self):
        """Return the instance state to be pickled."""
        return {field: getattr(self, field) for field in self.fields}

    def __ne__(self, other):
        match = self.__eq__(other)
        if match is not NotImplemented:
            match = not match
        return match

    def __reduce__(self):
        """
        Dynamically created classes at runtime cannot be pickled, due to not
        being defined at the top level of a module. As a result, we require to
        use the __reduce__ interface to allow 'pickle' to recreate this class
        instance, and dump and load instance state successfully.

        """
        return (MetadataManagerFactory, (self.cls,), self.__getstate__())

    def __repr__(self):
        args = ", ".join(
            [
                "{}={!r}".format(field, getattr(self, field))
                for field in self.fields
            ]
        )
        return "{}({})".format(self.__class__.__name__, args)

    def __setstate__(self, state):
        """Set the instance state when unpickling."""
        for field, value in state.items():
            setattr(self, field, value)

    @property
    def fields(self):
        """Return the name of the metadata members."""
        return self.cls._fields

    @property
    def values(self):
        fields = {field: getattr(self, field) for field in self.fields}
        return self.cls(**fields)

    # Restrict factory to appropriate metadata classes only.
    if not issubclass(cls, BaseMetadata):
        emsg = "Require a subclass of {!r}, got {!r}."
        raise TypeError(emsg.format(BaseMetadata.__name__, cls))

    # Check whether kwargs have valid fields for the specified metadata.
    if kwargs:
        extra = [field for field in kwargs.keys() if field not in cls._fields]
        if extra:
            bad = ", ".join(map(lambda field: "{!r}".format(field), extra))
            emsg = "Invalid {!r} field parameters, got {}."
            raise ValueError(emsg.format(cls.__name__, bad))

    # Define the name, (inheritance) bases and namespace of the dynamic class.
    name = "MetadataManager"
    bases = ()
    namespace = {
        "DEFAULT_NAME": cls.DEFAULT_NAME,
        "__init__": __init__,
        "__eq__": __eq__,
        "__getstate__": __getstate__,
        "__ne__": __ne__,
        "__reduce__": __reduce__,
        "__repr__": __repr__,
        "__setstate__": __setstate__,
        "fields": fields,
        "name": cls.name,
        "token": cls.token,
        "values": values,
    }

    # Account for additional "CubeMetadata" specialised class behaviour.
    if cls is CubeMetadata:
        namespace["_names"] = cls._names

    # Dynamically create the class.
    MetadataManagerClass = type(name, bases, namespace)
    # Now manufacture an instance of that class.
    manager = MetadataManagerClass(cls, **kwargs)

    return manager
