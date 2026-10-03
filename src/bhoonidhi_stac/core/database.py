from typing import Any

import psycopg
from psycopg import sql
from pypgstac.db import PgstacDB
from pypgstac.load import Loader, Methods
from pypgstac.migrate import Migrate

from bhoonidhi_stac.logger import get_console
from bhoonidhi_stac.schemas import DatabaseSchema


class DatabaseManager:
    def __init__(self, params: DatabaseSchema, verbose: bool = True):
        self.params = params
        self.console = get_console()

    # Required extensions for pgSTAC
    REQUIRED_EXTENSIONS = [
        {"name": "btree_gist", "min_version": None},
        {"name": "postgis", "min_version": "3.0.0"},
    ]

    def _validate_dsn(self) -> bool:
        try:
            with psycopg.connect(self.params.dsn) as _:
                self.console.print("[green]✅ PostgreSQL connection is up![/green]")
                return True
        except Exception:
            self.console.print_exception()
            raise ValueError("Invalid DSN — could not connect to PostgreSQL.")

    def _ensure_database_exists(self):
        admin_dsn = self.params.dsn
        try:
            with psycopg.connect(admin_dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM pg_database WHERE datname = %s",
                        (self.params.database,),
                    )
                    if cur.fetchone():
                        self.console.print(
                            f"[green]✅ Database '{self.params.database}' exists.[/green]"
                        )
                    else:
                        self.console.print(
                            f"[yellow]⚠️ Database '{self.params.database}' not found. Creating...[/yellow]"
                        )
                        cur.execute(
                            f"CREATE DATABASE {sql.Identifier(self.params.database).as_string(conn)}"
                        )
                        self.console.print(
                            f"[green]✅ Database '{self.params.database}' created successfully.[/green]"
                        )
        except Exception as e:
            self.console.print_exception()
            self.console.print(
                f"[bold red]❌ Failed to check or create database: {e}[/bold red]"
            )
            raise

    def _check_extension_availability(self, cur, extension_name: str) -> bool:
        """
        Check if extension is available on the PostgreSQL server.

        Args:
            cur: Database cursor
            extension_name: Name of extension to check

        Returns:
            True if available, False otherwise
        """
        cur.execute(
            "SELECT name, default_version FROM pg_available_extensions WHERE name = %s",
            (extension_name,),
        )
        result = cur.fetchone()

        if result:
            self.console.print(f"   ├─ {extension_name}: available (v{result[1]})")
            return True
        else:
            return False

    def _check_extension_enabled(
        self, cur, extension_name: str
    ) -> tuple[bool, str | None]:
        """
        Check if extension is enabled in current database.

        Args:
            cur: Database cursor
            extension_name: Name of extension to check

        Returns:
            Tuple of (is_enabled, version)
        """
        cur.execute(
            "SELECT extname, extversion FROM pg_extension WHERE extname = %s",
            (extension_name,),
        )
        result = cur.fetchone()

        if result:
            return True, result[1]
        else:
            return False, None

    def _create_extension(self, cur, extension_name: str) -> bool:
        """
        Create extension in current database.

        Args:
            cur: Database cursor
            extension_name: Name of extension to create

        Returns:
            True if successful, False otherwise

        Raises:
            ValueError: If insufficient permissions or other error
        """
        try:
            # Use sql.Identifier to safely handle extension name
            query = sql.SQL("CREATE EXTENSION IF NOT EXISTS {}").format(
                sql.Identifier(extension_name)
            )
            cur.execute(query)

            self.console.print("   │  └─ ✅ Created successfully")
            return True

        except psycopg.errors.InsufficientPrivilege as e:
            error_msg = f"""[bold red]❌ Cannot create extension '{extension_name}' — insufficient privileges[/bold red]"""
            self.console.print(error_msg)
            raise ValueError(
                f"Insufficient privileges to create extension '{extension_name}'"
            ) from e

        except Exception as e:
            self.console.print(
                f"[bold red]❌ Failed to create extension '{extension_name}': {e}[/bold red]"
            )
            raise

    def _verify_postgis_version(self, cur) -> str | None:
        """
        Verify PostGIS installation and get version.

        Args:
            cur: Database cursor

        Returns:
            PostGIS version string or None if not available
        """
        try:
            cur.execute("SELECT PostGIS_Version()")
            version = cur.fetchone()[0]
            return version
        except Exception:
            return None

    def ensure_extensions(self) -> bool:
        """
        Ensure required PostgreSQL extensions are installed and enabled.

        Returns:
            True if all extensions are ready

        Raises:
            ValueError: If extensions unavailable or cannot be created
        """

        # Connect to target database with autocommit

        try:
            with psycopg.connect(self.params.dsn, autocommit=True) as conn:
                with conn.cursor() as cur:
                    # 1: Check availability
                    unavailable = []
                    for ext in self.REQUIRED_EXTENSIONS:
                        ext_name = ext["name"]
                        if not self._check_extension_availability(
                            cur,
                            ext_name,  # ty:ignore[invalid-argument-type]
                        ):
                            unavailable.append(ext_name)

                    if unavailable:
                        error_msg = f"""[bold red]❌ Required extensions not available on PostgreSQL server:[/bold red]{", ".join(unavailable)}"""
                        self.console.print(error_msg)
                        raise ValueError(
                            f"Extensions not available: {', '.join(unavailable)}"
                        )

                    # 2: Check which are enabled and create missing ones
                    extensions_status = []
                    for ext in self.REQUIRED_EXTENSIONS:
                        ext_name = ext["name"]
                        is_enabled, version = self._check_extension_enabled(
                            cur,
                            ext_name,  # ty:ignore[invalid-argument-type]
                        )

                        if is_enabled:
                            self.console.print(
                                f"   │  └─ ✅ Already enabled (v{version})"
                            )
                            extensions_status.append((ext_name, True, version))
                        else:
                            self.console.print("   │  └─ ⚠️  Not enabled, creating...")
                            self._create_extension(
                                cur,
                                ext_name,  # ty:ignore[invalid-argument-type]
                            )

                            # Verify it was created
                            is_enabled, version = self._check_extension_enabled(
                                cur,
                                ext_name,  # ty:ignore[invalid-argument-type]
                            )
                            extensions_status.append((ext_name, is_enabled, version))

                    # 3: Verify PostGIS
                    if any(
                        ext["name"] == "postgis" for ext in self.REQUIRED_EXTENSIONS
                    ):
                        postgis_full_version = self._verify_postgis_version(cur)
                        if postgis_full_version:
                            self.console.print(
                                f"\n✅ PostGIS verification: {postgis_full_version}"
                            )

                    # Final summary
                    self.console.print(
                        "\n[green]✅ All required extensions are ready[/green]"
                    )
                    for ext_name, enabled, version in extensions_status:
                        self.console.print(f"   └─ {ext_name}: v{version}")

                    return True

        except psycopg.OperationalError as e:
            self.console.print(
                f"[bold red]❌ Cannot connect to database '{self.params.database}'[/bold red]"
            )
            self.console.print(f"   Error: {e}")
            self.console.print(
                "\n   Ensure database was created first (call _ensure_database_exists())"
            )
            raise
        except Exception:
            self.console.print_exception()
            raise

    def ensure_pgstac_schema(self) -> bool:
        """
        Initialise or migrate pgSTAC schema using pypgstac.

        Returns:
            True if schema is ready

        Raises:
            RuntimeError: If migration fails
        """
        self.console.print(
            f"\n🔄 Initializing pgSTAC schema in '{self.params.database}'..."
        )

        try:
            # Use pypgstac's PgstacDB context manager
            with PgstacDB(dsn=self.params.dsn) as db:
                # Check current version before migration
                current_version = db.version
                if current_version:
                    self.console.print(
                        f"   ├─ Current pgSTAC version: {current_version}"
                    )
                else:
                    self.console.print("   ├─ No existing pgSTAC schema found")

                # Run migrations
                self.console.print("   ├─ Running migrations...")

                migrate = Migrate(db)
                migrate.run_migration()

                # Verify new version
                new_version = db.version
                self.console.print(
                    f"   ├─ pgSTAC version after migration: {new_version}"
                )

                # Verify core tables exist
                self._verify_pgstac_tables(db)

                self.console.print("\n[green]✅ pgSTAC schema is ready[/green]")

                # Enable Auto Extent
                self._enable_pgstac_auto_extent(conn=db.connect())

                return True

        except Exception as e:
            self.console.print(f"[bold red]❌ pgSTAC migration failed: {e}[/bold red]")
            self.console.print_exception()
            raise RuntimeError(f"pgSTAC migration failed: {e}") from e

    def _verify_pgstac_tables(self, db: PgstacDB) -> None:
        """
        Verify core pgSTAC tables exist.

        Args:
            db: PgstacDB connection instance
        """
        required_tables = ["collections", "items", "searches", "pgstac_settings"]

        with db.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'pgstac' 
                    AND table_name = ANY(%s)
                """,
                (required_tables,),
            )

            found_tables = {row[0] for row in cur.fetchall()}
            missing = set(required_tables) - found_tables

            if missing:
                raise RuntimeError(f"Missing pgSTAC tables: {missing}")

            self.console.print(
                f"   ├─ Verified tables: {', '.join(sorted(found_tables))}"
            )

    def get_pgstac_version(self) -> str | None:
        """
        Get current pgSTAC version from database.

        Returns:
            Version string or None if not installed
        """

        try:
            with PgstacDB(dsn=self.params.dsn) as db:
                return db.version
        except Exception:
            return None

    def _enable_pgstac_auto_extent(self, conn):
        """Sets the PgSTAC setting to automatically update collection extents."""
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pgstac.pgstac_settings (name, value)
                    VALUES ('update_collection_extent', 'true')
                    ON CONFLICT (name) DO UPDATE SET value = 'true';
                """
                )
            self.console.print(
                "[green]✅ pgSTAC automatic extent update enabled.[/green]"
            )
        except Exception:
            self.console.print_exception()

    def register_collection(self, collection: dict[str, Any]) -> str:
        """
        Register a STAC collection in pgSTAC.

        Args:
            collection: STAC Collection dict with required fields:
                - id: Unique collection identifier
                - type: "Collection"
                - stac_version: "1.0.0"
                - description: Collection description
                - license: License identifier
                - extent: Spatial and temporal extent
                - links: List of link objects

        Returns:
            Collection ID

        Raises:
            ValueError: If collection is invalid
            RuntimeError: If registration fails
        """
        # Validate minimum required fields
        required_fields = ["id", "type", "description", "license", "extent", "links"]
        missing = [f for f in required_fields if f not in collection]
        if missing:
            raise ValueError(f"Collection missing required fields: {missing}")

        if collection.get("type") != "Collection":
            raise ValueError("Collection 'type' must be 'Collection'")

        # Ensure stac_version is set
        if "stac_version" not in collection:
            collection["stac_version"] = "1.0.0"

        collection_id = collection["id"]

        self.console.print(f"\n📦 Registering collection '{collection_id}'...")

        try:
            with PgstacDB(dsn=self.params.dsn) as db:
                loader = Loader(db=db)

                # Check if collection exists
                existing = self._get_collection(db, collection_id)

                if existing:
                    self.console.print("   ├─ Collection exists, updating...")
                    # Use upsert to update
                    loader.load_collections(
                        file=self._dict_to_ndjson_iter([collection]),
                        insert_mode=Methods.upsert,
                    )
                else:
                    self.console.print("   ├─ Creating new collection...")
                    loader.load_collections(
                        file=self._dict_to_ndjson_iter([collection]),
                        insert_mode=Methods.insert,
                    )

                # The extent follows the scenes, as pgSTAC's automatic update
                # sets it whenever scenes are saved. A collection that gets
                # no new scenes would otherwise keep the registered extent.
                if self._set_extent_from_scenes(db, collection_id):
                    self.console.print("   ├─ Extent set from its scenes")
                else:
                    self.console.print("   ├─ No scenes yet, registered extent kept")

                self.console.print(
                    f"[green]   └─ ✅ Collection '{collection_id}' registered[/green]"
                )

                return collection_id

        except Exception as e:
            self.console.print(
                f"[bold red]❌ Failed to register collection: {e}[/bold red]"
            )
            self.console.print_exception()
            raise RuntimeError(f"Collection registration failed: {e}") from e

    def _set_extent_from_scenes(self, db: PgstacDB, collection_id: str) -> bool:
        """
        Set a collection's extent (dates and box) from the scenes it holds.

        Uses pgSTAC's ``collection_extent``, which reads the per-partition
        summary, the same value its automatic update writes: the first to
        the newest scene date, and the box around every footprint.

        Args:
            db: PgstacDB connection
            collection_id: Collection identifier

        Returns:
            True if the extent was set, False if the collection holds no
            scenes (its registered extent stays)
        """
        updated = db.query_one(
            """
            UPDATE pgstac.collections
            SET content = jsonb_set(content, '{extent}', e.extent)
            FROM (SELECT pgstac.collection_extent(%s, FALSE) AS extent) AS e
            WHERE id = %s AND e.extent IS NOT NULL
            RETURNING id
            """,
            [collection_id, collection_id],
        )
        return updated is not None

    def _get_collection(self, db: PgstacDB, collection_id: str) -> dict | None:
        """
        Get collection by ID from pgSTAC.

        Args:
            db: PgstacDB connection
            collection_id: Collection identifier

        Returns:
            Collection dict or None if not found
        """
        with db.connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT content FROM pgstac.collections WHERE id = %s",
                (collection_id,),
            )
            result = cur.fetchone()
            return result[0] if result else None

    def _dict_to_ndjson_iter(self, items: list[dict]):
        """
        Convert list of dicts to newline-delimited JSON iterator.

        pypgstac's loader expects an iterable of JSON strings.

        Args:
            items: List of dictionaries

        Yields:
            JSON string for each item
        """
        import json

        for item in items:
            yield json.dumps(item)

    def upsert_items(
        self, items: list[dict[str, Any]], collection_id: str, method: str = "upsert"
    ) -> dict[str, int]:
        """
        Insert or update STAC items in pgSTAC.

        Args:
            items: List of STAC Item dicts (or portal result dicts to transform)
            collection_id: Target collection ID
            method: Insert method - 'insert', 'insert_ignore', or 'upsert'

        Returns:
            Dict with counts: {'inserted': n, 'updated': n, 'errors': n}

        Raises:
            RuntimeError: If bulk insert fails
        """
        if not items:
            return {"inserted": 0, "updated": 0, "errors": 0}

        # Map method string to pypgstac Methods enum
        method_map = {
            "insert": Methods.insert,
            "insert_ignore": Methods.ignore,
            "upsert": Methods.upsert,
        }

        if method not in method_map:
            raise ValueError(
                f"Invalid method '{method}'. Use: {list(method_map.keys())}"
            )

        self.console.print(
            f"\n📥 Loading {len(items)} items into collection '{collection_id}'..."
        )
        self.console.print(f"   ├─ Method: {method}")

        try:
            with PgstacDB(dsn=self.params.dsn) as db:
                loader = Loader(db=db)

                # Transform portal dicts to STAC items if needed
                stac_items = [
                    self._ensure_stac_item(item, collection_id) for item in items
                ]

                # Filter out any None results (failed transformations)
                valid_items = [i for i in stac_items if i is not None]
                error_count = len(stac_items) - len(valid_items)

                if valid_items:
                    loader.load_items(
                        file=self._dict_to_ndjson_iter(valid_items),
                        insert_mode=method_map[method],
                    )

                result = {
                    "inserted": len(valid_items) if method != "upsert" else 0,
                    "updated": len(valid_items) if method == "upsert" else 0,
                    "errors": error_count,
                }

                self.console.print(
                    f"[green]   └─ ✅ Loaded {len(valid_items)} items[/green]"
                )
                if error_count:
                    self.console.print(
                        f"[yellow]      ⚠️ {error_count} items failed transformation[/yellow]"
                    )

                return result

        except Exception as e:
            self.console.print(f"[bold red]❌ Failed to load items: {e}[/bold red]")
            self.console.print_exception()
            raise RuntimeError(f"Item loading failed: {e}") from e

    def _ensure_stac_item(self, item: dict, collection_id: str) -> dict | None:
        """
        Ensure item is valid STAC Item format, transforming if needed.

        If item is already STAC format (has 'type': 'Feature'), pass through.
        If item is portal format (has 'SATELLITE', 'DOP', etc.), transform.

        Args:
            item: Item dict (either STAC or portal format)
            collection_id: Collection to assign

        Returns:
            STAC Item dict or None if transformation fails
        """
        # Already a STAC item?
        if item.get("type") == "Feature" and "geometry" in item:
            # Ensure collection is set
            item["collection"] = collection_id
            return item

        # Transform portal format to STAC
        try:
            return self._transform_bhoonidhi_scene_to_stac(item, collection_id)
        except Exception as e:
            self.console.print(
                f"[yellow]   ⚠️ Transform failed for {item.get('ID', 'unknown')}: {e}[/yellow]"
            )
            return None

    def _transform_bhoonidhi_scene_to_stac(
        self, scene_meta: dict, collection_id: str
    ) -> dict:
        """Transform a Bhoonidhi portal scene dict into a STAC Item.

        Uses the bhoonidhi-downloader's URL builders and classifiers
        to produce correct quicklook/metadata URLs and rich properties.
        """
        from datetime import datetime

        from bhoonidhi_downloader.core.search.availability import (
            access_of,
            availability_of,
            is_downloadable,
        )
        from bhoonidhi_downloader.core.search.utils import (
            get_quicklook_url,
            get_scene_meta_url,
            scene_resolution,
        )

        # ── coordinates ──────────────────────────────────────────

        def to_float(val):
            try:
                return float(val)
            except (TypeError, ValueError):
                return 0.0

        nw_lat = to_float(scene_meta.get("ImgCrnNWLat") or scene_meta.get("CrnNWLat"))
        nw_lon = to_float(scene_meta.get("ImgCrnNWLon") or scene_meta.get("CrnNWLon"))
        ne_lat = to_float(scene_meta.get("ImgCrnNELat") or scene_meta.get("CrnNELat"))
        ne_lon = to_float(scene_meta.get("ImgCrnNELon") or scene_meta.get("CrnNELon"))
        se_lat = to_float(scene_meta.get("ImgCrnSELat") or scene_meta.get("CrnSELat"))
        se_lon = to_float(scene_meta.get("ImgCrnSELon") or scene_meta.get("CrnSELon"))
        sw_lat = to_float(scene_meta.get("ImgCrnSWLat") or scene_meta.get("CrnSWLat"))
        sw_lon = to_float(scene_meta.get("ImgCrnSWLon") or scene_meta.get("CrnSWLon"))

        geometry = {
            "type": "Polygon",
            "coordinates": [
                [
                    [nw_lon, nw_lat],
                    [ne_lon, ne_lat],
                    [se_lon, se_lat],
                    [sw_lon, sw_lat],
                    [nw_lon, nw_lat],
                ]
            ],
        }

        lons = [nw_lon, ne_lon, se_lon, sw_lon]
        lats = [nw_lat, ne_lat, se_lat, sw_lat]
        bbox = [min(lons), min(lats), max(lons), max(lats)]

        # ── datetime ─────────────────────────────────────────────

        dop_str = scene_meta.get("DOP", "")
        try:
            dop = datetime.strptime(dop_str, "%d-%b-%Y")  # noqa: DTZ007
            datetime_str = dop.strftime("%Y-%m-%dT00:00:00Z")
        except ValueError:
            datetime_str = datetime.utcnow().strftime("%Y-%m-%dT00:00:00Z")  # noqa: DTZ003

        # ── access / availability (SDK classifiers) ──────────────

        access = access_of(scene_meta)
        availability = availability_of(scene_meta)
        downloadable = is_downloadable(scene_meta)

        # ── resolution (looked up from archive manifest) ─────────

        gsd_str = scene_resolution(scene_meta)
        gsd = None
        if gsd_str and gsd_str != "-":
            try:
                gsd = float(gsd_str)
            except (ValueError, TypeError):
                pass

        # ── STAC-standard properties alongside raw portal fields ─
        # Portal fields whose meaning differs from a STAC extension field stay
        # as raw fields only. PATHNO numbers ground tracks by their position
        # on the ground, while the sat extension's relative orbit counts
        # orbits in the order they are flown. PASS_TYPE holds the portal's
        # own codes (SSR, PLD, X, D, N and others), not ascending or
        # descending, and ROLL is a signed roll angle, not an azimuth.

        properties = {
            # preserve all raw portal fields
            **scene_meta,
            # STAC core
            "datetime": datetime_str,
            "platform": str(scene_meta.get("SATELLITE", "")).lower(),
            "instruments": [str(scene_meta.get("SENSOR", ""))],
            # STAC extensions
            "gsd": gsd,
            # bhoonidhi extensions
            "bhoonidhi:access": access.value,
            "bhoonidhi:availability": availability.value,
            "bhoonidhi:downloadable": downloadable,
            "bhoonidhi:product_type": scene_meta.get("PRODTYPE"),
            "bhoonidhi:product_code": scene_meta.get("PRODCODE"),
            "bhoonidhi:selection": scene_meta.get("SELECTION"),
            "bhoonidhi:quality_score": scene_meta.get("QUALITY_SCORE"),
            "bhoonidhi:downloaded": False,
            "bhoonidhi:status": "L0",
            "bhoonidhi:cloud_cover": None,
        }

        # ── assets (SDK URL builders) ────────────────────────────

        assets = {}

        quicklook_url = get_quicklook_url(scene_meta)
        if quicklook_url:
            # extension depends on TABLETYPE (SMETA -> .jpeg, PMETA -> .jpg)
            ext = quicklook_url.rsplit(".", 1)[-1] if "." in quicklook_url else "jpg"
            assets["thumbnail"] = {
                "href": quicklook_url,
                "type": f"image/{ext}",
                "roles": ["thumbnail"],
            }

        metadata_url = get_scene_meta_url(scene_meta)
        if metadata_url:
            # only present for open-data + PMETA scenes; handles
            # Sentinel-1/2, Novasar, NISAR naming quirks
            assets["metadata"] = {
                "href": metadata_url,
                "type": "application/xml",
                "roles": ["metadata"],
            }

        # ── assemble ─────────────────────────────────────────────

        return {
            "type": "Feature",
            "stac_version": "1.0.0",
            "stac_extensions": [],
            "id": scene_meta.get("ID") or scene_meta.get("FILENAME"),
            "geometry": geometry,
            "bbox": bbox,
            "datetime": datetime_str,
            "collection": collection_id,
            "properties": properties,
            "links": [],
            "assets": assets,
        }

    def get_collection_item_count(self, collection_id: str) -> int:
        """
        Get count of items in a collection.

        Args:
            collection_id: Collection identifier

        Returns:
            Number of items
        """

        with PgstacDB(dsn=self.params.dsn) as db, db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM pgstac.items WHERE collection = %s",
                    (collection_id,),
                )
                return cur.fetchone()[0]

    def delete_collection(self, collection_id: str, cascade_items: bool = True) -> None:
        """
        Delete a STAC collection and optionally all its items from pgSTAC.

        Args:
            collection_id: ID of the collection to delete.
            cascade_items: If True, delete all items in this collection first.

        Raises:
            RuntimeError: If deletion fails.
        """
        self.console.print(f"\n[red]🗑 Deleting collection '{collection_id}'[/red]")

        try:
            with PgstacDB(dsn=self.params.dsn) as db:
                with db.connect() as conn:
                    with conn.cursor() as cur:
                        # 1. Optionally delete items first
                        if cascade_items:
                            self.console.print(
                                f"   ├─ Deleting items for collection '{collection_id}'..."
                            )
                            cur.execute(
                                "DELETE FROM pgstac.items WHERE collection = %s",
                                (collection_id,),
                            )
                            deleted_items = cur.rowcount
                            self.console.print(
                                f"   │  └─ Removed {deleted_items} item(s)"
                            )

                        # 2. Delete the collection row itself
                        self.console.print(
                            f"   ├─ Deleting collection metadata for '{collection_id}'..."
                        )
                        cur.execute(
                            "DELETE FROM pgstac.collections WHERE id = %s",
                            (collection_id,),
                        )
                        deleted_collections = cur.rowcount

                        if deleted_collections == 0:
                            self.console.print(
                                f"[yellow]   │  └─ No collection with id '{collection_id}' found[/yellow]"
                            )
                        else:
                            self.console.print(
                                f"[green]   │  └─ Collection '{collection_id}' deleted[/green]"
                            )

                    conn.commit()

        except Exception as e:
            self.console.print(
                f"[bold red]❌ Failed to delete collection '{collection_id}': {e}[/bold red]"
            )
            self.console.print_exception()
            raise RuntimeError(
                f"Collection deletion failed for '{collection_id}': {e}"
            ) from e
