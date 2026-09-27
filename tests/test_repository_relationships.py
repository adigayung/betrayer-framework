"""Task 09.3 — Repository & Relationships tests.

All tests use the same *fake in-memory engine/connection* as the Task 09.2
suite (imported from ``test_query_orm``); never a real database.  The proof is::

    Repository -> ORM Model -> Query Builder -> Compiler -> Dialect -> Connection

runs end to end, relationships resolve to predictable queries, and no
SQLite/PostgreSQL/MySQL-specific code exists anywhere in the core.
"""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from betrayer.data import (
    BaseRepository,
    BelongsTo,
    BoundRelationship,
    DatabaseManager,
    HasMany,
    HasOne,
    ManyToMany,
    ORMField,
    ORMModel,
    Query,
    Relationship,
    RepositoryError,
)
from betrayer.data.exceptions import ModelError
from betrayer.data.models import Field, Model
from test_query_orm import FakeConnection, FakeEngine  # noqa: E402 - shared test double


# ---------------------------------------------------------------------------
# Models under test (module level so string targets can be resolved)
# ---------------------------------------------------------------------------


class User(ORMModel):
    __table__ = "users"

    id = ORMField(int, primary_key=True)
    name = ORMField(str)
    email = ORMField(str, nullable=True)
    active = ORMField(bool, default=True)
    age = ORMField(int, nullable=True)

    posts = HasMany("Post", foreign_key="author_id")
    profile = HasOne("Profile")  # FK default: user_id


class Post(ORMModel):
    __table__ = "posts"

    id = ORMField(int, primary_key=True)
    title = ORMField(str)
    author_id = ORMField(int, nullable=True)
    published = ORMField(bool, default=False)

    author = BelongsTo("User")  # FK default: author_id


class Profile(ORMModel):
    __table__ = "profiles"

    id = ORMField(int, primary_key=True)
    user_id = ORMField(int, nullable=True)
    bio = ORMField(str, nullable=True)


class Category(ORMModel):
    __table__ = "categories"

    id = ORMField(int, primary_key=True)
    name = ORMField(str)


class Product(ORMModel):
    __table__ = "products"

    id = ORMField(int, primary_key=True)
    sku = ORMField(str)

    categories = ManyToMany("Category")  # pivot default: products_categories


class Widget(ORMModel):
    __table__ = "widgets"

    id = ORMField(int, primary_key=True)


class Dashboard(ORMModel):
    __table__ = "dashboards"

    id = ORMField(int, primary_key=True)

    widgets = HasMany(Widget)  # FK default: dashboard_id


_ALL_MODELS = (User, Post, Profile, Category, Product, Widget, Dashboard)


@pytest.fixture()
def manager() -> DatabaseManager:
    engine = FakeEngine("default")
    mgr = DatabaseManager(engine)
    mgr.connect()
    for model in _ALL_MODELS:
        model.__connection__ = mgr
    conn = mgr.connection
    assert isinstance(conn, FakeConnection)
    conn.seed(
        "users",
        [
            {"id": 1, "name": "Alice", "email": "alice@example.com", "active": True, "age": 30},
            {"id": 2, "name": "Bob", "email": "bob@example.com", "active": False, "age": 25},
        ],
    )
    conn.seed(
        "posts",
        [
            {"id": 1, "title": "Hello", "author_id": 1, "published": True},
            {"id": 2, "title": "Draft", "author_id": 1, "published": False},
            {"id": 3, "title": "Orphan", "author_id": None, "published": True},
        ],
    )
    conn.seed("profiles", [{"id": 1, "user_id": 1, "bio": "hi"}])
    conn.seed(
        "categories",
        [{"id": 1, "name": "Tech"}, {"id": 2, "name": "News"}],
    )
    conn.seed("products", [{"id": 1, "sku": "SKU-1"}, {"id": 2, "sku": "SKU-2"}])
    conn.seed(
        "products_categories",
        [
            {"product_id": 1, "category_id": 1},
            {"product_id": 1, "category_id": 2},
        ],
    )
    return mgr


def _repository(model=User):
    return model.repository()


# ---------------------------------------------------------------------------
# Repository — construction / validation
# ---------------------------------------------------------------------------


def test_repository_requires_orm_model():
    with pytest.raises(RepositoryError):
        BaseRepository(object)


def test_repository_rejects_legacy_model():
    """The legacy DTO ``Model`` is not an ORM model -> RepositoryError."""

    class Legacy(Model):
        name = Field(str)

    with pytest.raises(RepositoryError):
        BaseRepository(Legacy)


def test_repository_holds_explicit_model(manager):
    repo = _repository(User)
    assert isinstance(repo, BaseRepository)
    assert repo.model is User
    assert repo.model_class is User


# ---------------------------------------------------------------------------
# Repository — CRUD
# ---------------------------------------------------------------------------


def test_repository_find(manager):
    user = _repository().find(1)
    assert isinstance(user, User)
    assert user.name == "Alice"


def test_repository_find_missing_returns_none(manager):
    assert _repository().find(999) is None


def test_repository_find_or_fail(manager):
    assert _repository().find_or_fail(1).name == "Alice"


def test_repository_find_or_fail_raises_with_context(manager):
    with pytest.raises(RepositoryError) as excinfo:
        _repository().find_or_fail(999)
    assert excinfo.value.context["model"] == "User"
    assert excinfo.value.context["identifier"] == 999


def test_repository_all(manager):
    users = _repository().all()
    assert [u.name for u in users] == ["Alice", "Bob"]
    assert all(isinstance(u, User) for u in users)


def test_repository_where_returns_composable_query(manager):
    query = _repository().where("active", True)
    assert isinstance(query, Query)
    names = [u.name for u in query.order_by("id", "desc").get()]
    assert names == ["Alice"]


def test_repository_count(manager):
    assert _repository().count() == 2
    assert _repository(Post).count() == 3


def test_repository_exists(manager):
    repo = _repository()
    assert repo.exists() is True
    assert repo.exists(email="bob@example.com") is True
    assert repo.exists(email="nobody@example.com") is False


def test_repository_create(manager):
    repo = _repository(Post)
    post = repo.create(title="New", author_id=1, published=True)
    assert isinstance(post, Post)
    assert post.id is not None
    assert repo.find(post.id).title == "New"
    assert repo.count() == 4


def test_repository_create_accepts_mapping(manager):
    repo = _repository(Post)
    post = repo.create({"title": "FromDict", "author_id": 1})
    assert post.title == "FromDict"


def test_repository_update(manager):
    repo = _repository()
    affected = repo.update(2, {"name": "Bobby", "active": True})
    assert affected == 1
    assert repo.find(2).name == "Bobby"
    assert repo.find(2).active is True


def test_repository_update_requires_identifier(manager):
    with pytest.raises(RepositoryError):
        _repository().update(None, {"name": "X"})


def test_repository_update_requires_values(manager):
    with pytest.raises(RepositoryError):
        _repository().update(1, {})


def test_repository_delete(manager):
    repo = _repository(Post)
    assert repo.delete(3) == 1
    assert repo.find(3) is None
    assert repo.count() == 2


def test_repository_delete_requires_identifier(manager):
    with pytest.raises(RepositoryError):
        _repository().delete(None)


# ---------------------------------------------------------------------------
# Repository — parameterization / safety contract preserved
# ---------------------------------------------------------------------------


def test_repository_where_is_parameterized(manager):
    conn = manager.connection
    assert isinstance(conn, FakeConnection)
    rows = _repository().where("name", "Alice' OR '1'='1").get()
    assert rows == []
    bound = [p for _, params in conn._executed for p in (params or [])]
    assert "Alice' OR '1'='1" in bound


def test_repository_update_uses_primary_key_where(manager):
    """update/delete always carry a ``where`` (never a full-table write)."""
    conn = manager.connection
    assert isinstance(conn, FakeConnection)
    _repository().update(1, {"name": "Zed"})
    update_sql = [q for q, _ in conn._executed if q.upper().startswith("UPDATE")]
    assert update_sql and "WHERE" in update_sql[-1]


# ---------------------------------------------------------------------------
# Repository — metadata / introspection
# ---------------------------------------------------------------------------


def test_repository_introspect(manager):
    meta = _repository().introspect()
    assert meta["type"] == "repository"
    assert meta["name"] == "BaseRepository"
    assert meta["model"] == "User"
    assert meta["table"] == "users"
    assert meta["primary_key"] == "id"
    # relationships are part of repository metadata
    rel_names = {r["name"] for r in meta["relationships"]}
    assert rel_names == {"posts", "profile"}


def test_repository_subclass_can_add_query_methods(manager):
    class UserRepository(BaseRepository[User]):
        def active(self) -> List[User]:
            return self.where("active", True).get()

    repo = UserRepository(User)
    assert isinstance(repo, BaseRepository)
    assert [u.name for u in repo.active()] == ["Alice"]
    assert repo.introspect()["name"] == "UserRepository"


# ---------------------------------------------------------------------------
# Model <-> Repository
# ---------------------------------------------------------------------------


def test_model_default_repository(manager):
    repo = User.repository()
    assert isinstance(repo, BaseRepository)
    assert repo.model is User
    assert repo.find(1).name == "Alice"


def test_model_custom_repository(manager):
    class Project(ORMModel):
        __table__ = "projects"
        id = ORMField(int, primary_key=True)

    class ProjectRepository(BaseRepository[Project]):
        pass

    Project.__repository__ = ProjectRepository
    Project.__connection__ = manager
    repo = Project.repository()
    assert isinstance(repo, ProjectRepository)
    assert repo.model is Project


# ---------------------------------------------------------------------------
# Relationships — belongs_to
# ---------------------------------------------------------------------------


def test_belongs_to_accessor_returns_query(manager):
    post = Post.query().where("id", 1).first()
    bound = post.author
    assert isinstance(bound, object)
    assert bound.kind == "belongs_to"
    query = post.author()
    assert isinstance(query, Query)
    author = query.first()
    assert isinstance(author, User)
    assert author.name == "Alice"


def test_belongs_to_null_fk_is_empty(manager):
    orphan = Post.query().where("id", 3).first()
    assert orphan.author_id is None
    assert orphan.author().first() is None
    assert orphan.author().get() == []


def test_belongs_to_missing_row_is_none(manager):
    post = Post(id=99, title="Ghost", author_id=999)
    assert post.author().first() is None


# ---------------------------------------------------------------------------
# Relationships — has_many / has_one
# ---------------------------------------------------------------------------


def test_has_many(manager):
    user = User.query().where("id", 1).first()
    posts = user.posts().get()
    assert [p.title for p in posts] == ["Hello", "Draft"]
    assert all(isinstance(p, Post) for p in posts)


def test_has_many_is_composable(manager):
    user = User.query().where("id", 1).first()
    published = user.posts().where("published", True).get()
    assert [p.title for p in published] == ["Hello"]


def test_has_one(manager):
    user = User.query().where("id", 1).first()
    profile = user.profile().first()
    assert isinstance(profile, Profile)
    assert profile.bio == "hi"


def test_has_one_missing_is_none(manager):
    bob = User.query().where("id", 2).first()
    assert bob.profile().first() is None


def test_has_many_empty_for_missing_owner(manager):
    ghost = User(id=999, name="Ghost")
    assert ghost.posts().get() == []


# ---------------------------------------------------------------------------
# Relationships — many_to_many
# ---------------------------------------------------------------------------


def test_many_to_many(manager):
    product = Product.query().where("id", 1).first()
    categories = product.categories().get()
    assert sorted(c.name for c in categories) == ["News", "Tech"]
    assert all(isinstance(c, Category) for c in categories)


def test_many_to_many_empty(manager):
    product = Product.query().where("id", 2).first()
    assert product.categories().get() == []


def test_many_to_many_is_composable(manager):
    product = Product.query().where("id", 1).first()
    only = product.categories().where("name", "Tech").get()
    assert [c.name for c in only] == ["Tech"]


# ---------------------------------------------------------------------------
# Relationships — descriptors / metadata / defaults
# ---------------------------------------------------------------------------


def test_relationship_descriptor_class_vs_instance(manager):
    user = User.query().where("id", 1).first()
    # class access -> the Relationship itself
    assert isinstance(User.posts, Relationship)
    # instance access -> a bound accessor that yields a query
    assert isinstance(user.posts, BoundRelationship)
    assert isinstance(user.posts(), Query)


def test_relationship_metadata_via_model(manager):
    rels = User.orm_relationships()
    assert set(rels) == {"posts", "profile"}
    meta = User.meta()
    by_name = {r["name"]: r for r in meta["relationships"]}

    posts = by_name["posts"]
    assert posts["type"] == "has_many"
    assert posts["target"] == "Post"
    assert posts["cardinality"] == "many"
    assert posts["keys"] == {"foreign_key": "author_id", "local_key": "id"}

    profile = by_name["profile"]
    assert profile["type"] == "has_one"
    assert profile["target"] == "Profile"
    assert profile["cardinality"] == "one"
    assert profile["keys"] == {"foreign_key": "user_id", "local_key": "id"}


def test_relationship_metadata_belongs_to_defaults():
    rel = Post.relationship("author")
    assert rel.kind == "belongs_to"
    assert rel.to_dict() == {
        "name": "author",
        "type": "belongs_to",
        "target": "User",
        "cardinality": "one",
        "keys": {"foreign_key": "author_id", "target_key": "id"},
        "description": "",
    }


def test_relationship_metadata_has_many_defaults():
    rel = Dashboard.relationship("widgets")
    assert rel.to_dict()["keys"] == {
        "foreign_key": "dashboard_id",
        "local_key": "id",
    }


def test_relationship_metadata_many_to_many_defaults():
    rel = Product.relationship("categories")
    data = rel.to_dict()
    assert data["type"] == "many_to_many"
    assert data["target"] == "Category"
    assert data["cardinality"] == "many"
    assert data["keys"] == {
        "pivot": "products_categories",
        "pivot_local_key": "product_id",
        "pivot_foreign_key": "category_id",
        "local_key": "id",
        "target_key": "id",
    }


def test_bound_relationship_metadata(manager):
    user = User.query().where("id", 1).first()
    meta = user.posts.metadata()
    assert meta["name"] == "posts"
    assert meta["type"] == "has_many"
    assert user.posts.kind == "has_many"
    assert user.posts.target is Post
    assert user.posts.name == "posts"


# ---------------------------------------------------------------------------
# Relationships — invalid declarations / errors
# ---------------------------------------------------------------------------


def test_unknown_relationship_type_rejected():
    with pytest.raises(ModelError):
        Relationship("nonsense", User)
    with pytest.raises(ModelError):
        HasMany(123)  # not a model, string, or callable


def test_relationship_target_must_be_model():
    with pytest.raises(ModelError):
        HasMany(object)
    with pytest.raises(ModelError):
        BelongsTo("   ")


def test_relationship_name_collision_with_field_rejected():
    """A name used as both a field and a relationship is rejected."""

    class Base(ORMModel):
        __table__ = "base"
        id = ORMField(int, primary_key=True)
        thing = ORMField(int)

    with pytest.raises(ModelError):
        class Collision(Base):
            # "thing" is an inherited ORMField but declared here as a relationship
            thing = HasMany("Post")  # type: ignore[assignment]


def test_relationship_unknown_name_raises():
    with pytest.raises(ModelError):
        User.relationship("nope")


def test_relationship_unresolvable_string_target():
    class Lonely(ORMModel):
        __table__ = "lonely"
        id = ORMField(int, primary_key=True)
        ghosts = HasMany("DoesNotExist")

    with pytest.raises(ModelError):
        Lonely.relationship("ghosts").to_dict()


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


def test_legacy_repository_still_present():
    from betrayer.data.repository import Repository as LegacyRepository

    class Legacy(Model):
        id = Field(int)

    repo = LegacyRepository(Legacy, database=object())
    assert repo.model_class is Legacy
    with pytest.raises(NotImplementedError):
        repo.list()


def test_orm_model_meta_keeps_existing_keys(manager):
    meta = User.meta()
    for key in ("type", "name", "module", "table", "primary_key", "fields", "connection"):
        assert key in meta
