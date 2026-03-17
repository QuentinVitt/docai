import pytest

from docai.documentation.datatypes import (
    Attribute,
    DocItem,
    DocItemRef,
    DocItemType,
    FileDoc,
    FileDocType,
    PackageDoc,
    Parameter,
    ProjectDoc,
    RaisesEntry,
    ReturnValue,
)


# ---------------------------------------------------------------------------
# Parameter
# ---------------------------------------------------------------------------


def test_parameter_str_with_type():
    p = Parameter(name="value", type_hint="int", description="the value")
    assert str(p) == "value (int): the value"


def test_parameter_str_without_type():
    p = Parameter(name="value", description="the value")
    assert str(p) == "value: the value"


# ---------------------------------------------------------------------------
# Attribute
# ---------------------------------------------------------------------------


def test_attribute_str_with_type():
    a = Attribute(name="count", type_hint="int", description="item count")
    assert str(a) == "count (int): item count"


def test_attribute_str_without_type():
    a = Attribute(name="count", description="item count")
    assert str(a) == "count: item count"


# ---------------------------------------------------------------------------
# ReturnValue
# ---------------------------------------------------------------------------


def test_return_value_str_with_type():
    r = ReturnValue(type_hint="str", description="formatted name")
    assert str(r) == "(str) formatted name"


def test_return_value_str_without_type():
    r = ReturnValue(description="formatted name")
    assert str(r) == "formatted name"


# ---------------------------------------------------------------------------
# RaisesEntry
# ---------------------------------------------------------------------------


def test_raises_entry_str():
    r = RaisesEntry(exception="ValueError", description="when input is invalid")
    assert str(r) == "ValueError: when input is invalid"


# ---------------------------------------------------------------------------
# DocItemType
# ---------------------------------------------------------------------------


def test_doc_item_type_str():
    assert str(DocItemType.FUNCTION) == "function"
    assert str(DocItemType.METHOD) == "method"
    assert str(DocItemType.CLASS) == "class"
    assert str(DocItemType.DATATYPE) == "datatype"
    assert str(DocItemType.CONSTANT) == "constant"


# ---------------------------------------------------------------------------
# DocItemRef
# ---------------------------------------------------------------------------


def test_doc_item_ref_str_without_parent():
    ref = DocItemRef(name="my_func", type=DocItemType.FUNCTION)
    assert str(ref) == "my_func (function)"


def test_doc_item_ref_str_with_parent():
    ref = DocItemRef(name="get_user", type=DocItemType.METHOD, parent="UserService")
    assert str(ref) == "get_user (method, parent: UserService)"


# ---------------------------------------------------------------------------
# DocItem
# ---------------------------------------------------------------------------


def test_doc_item_str_function_minimal():
    item = DocItem(name="my_func", type=DocItemType.FUNCTION, description="Does something.")
    result = str(item)
    assert "function my_func:" in result
    assert "Does something." in result


def test_doc_item_str_function_full():
    item = DocItem(
        name="process",
        type=DocItemType.FUNCTION,
        description="Processes data.",
        parameters=[Parameter(name="data", type_hint="list", description="input data")],
        returns=ReturnValue(type_hint="dict", description="result"),
        raises=[RaisesEntry(exception="ValueError", description="on bad data")],
        side_effects="Writes to disk.",
    )
    result = str(item)
    assert "Parameters:" in result
    assert "data (list): input data" in result
    assert "Returns: (dict) result" in result
    assert "Raises:" in result
    assert "ValueError: on bad data" in result
    assert "Side effects: Writes to disk." in result


def test_doc_item_str_method_with_parent():
    item = DocItem(
        name="get_user",
        type=DocItemType.METHOD,
        parent="UserService",
        description="Fetches a user.",
    )
    result = str(item)
    assert "method get_user (UserService):" in result


def test_doc_item_str_class_with_attributes():
    item = DocItem(
        name="MyClass",
        type=DocItemType.CLASS,
        description="A simple class.",
        attributes=[Attribute(name="value", type_hint="int", description="stored value")],
        dunder_methods=["__init__", "__repr__"],
    )
    result = str(item)
    assert "Attributes:" in result
    assert "value (int): stored value" in result
    assert "Dunder methods: __init__, __repr__" in result


def test_doc_item_str_datatype_with_attributes():
    item = DocItem(
        name="Config",
        type=DocItemType.DATATYPE,
        description="A config dataclass.",
        attributes=[Attribute(name="debug", description="debug flag")],
    )
    result = str(item)
    assert "Attributes:" in result
    assert "debug: debug flag" in result


def test_doc_item_str_constant():
    item = DocItem(name="MAX_SIZE", type=DocItemType.CONSTANT, description="Maximum size.")
    result = str(item)
    assert "constant MAX_SIZE:" in result
    assert "Maximum size." in result
    # Constants should not have Parameters/Returns sections
    assert "Parameters:" not in result
    assert "Attributes:" not in result


# ---------------------------------------------------------------------------
# FileDocType
# ---------------------------------------------------------------------------


def test_file_doc_type_str():
    assert str(FileDocType.CODE) == "code"
    assert str(FileDocType.CONFIG) == "config"
    assert str(FileDocType.DOCS) == "docs"
    assert str(FileDocType.OTHER) == "other"
    assert str(FileDocType.SKIPPED) == "skipped"


# ---------------------------------------------------------------------------
# FileDoc
# ---------------------------------------------------------------------------


def test_file_doc_str_minimal():
    doc = FileDoc(path="src/foo.py", type=FileDocType.CODE, description="A module.")
    result = str(doc)
    assert "file: src/foo.py (code)" in result
    assert "A module." in result


def test_file_doc_str_with_items():
    doc = FileDoc(
        path="src/foo.py",
        type=FileDocType.CODE,
        description="A module.",
        items=[
            DocItemRef(name="MyClass", type=DocItemType.CLASS),
            DocItemRef(name="do_thing", type=DocItemType.FUNCTION),
        ],
    )
    result = str(doc)
    assert "Entities:" in result
    assert "MyClass (class)" in result
    assert "do_thing (function)" in result


def test_file_doc_str_skipped_no_description():
    doc = FileDoc(path="image.png", type=FileDocType.SKIPPED, description="")
    result = str(doc)
    assert "file: image.png (skipped)" in result
    # Empty description should not appear as a line
    assert "  \n" not in result


# ---------------------------------------------------------------------------
# PackageDoc
# ---------------------------------------------------------------------------


def test_package_doc_str_minimal():
    doc = PackageDoc(path="src/utils", description="Utility package.")
    result = str(doc)
    assert "package: src/utils" in result
    assert "Utility package." in result


def test_package_doc_str_with_files_and_subpackages():
    doc = PackageDoc(
        path="src",
        description="Root package.",
        files=["src/main.py", "src/config.py"],
        packages=["src/utils", "src/models"],
    )
    result = str(doc)
    assert "Files: src/main.py, src/config.py" in result
    assert "Sub-packages: src/utils, src/models" in result


# ---------------------------------------------------------------------------
# ProjectDoc
# ---------------------------------------------------------------------------


def test_project_doc_str_minimal():
    doc = ProjectDoc(name="MyProject", description="An AI tool.")
    result = str(doc)
    assert "project: MyProject" in result
    assert "An AI tool." in result


def test_project_doc_str_with_packages():
    doc = ProjectDoc(
        name="MyProject",
        description="An AI tool.",
        packages=["src/core", "src/api"],
    )
    result = str(doc)
    assert "Packages: src/core, src/api" in result
