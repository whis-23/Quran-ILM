import json
import os
import uuid
from datetime import datetime

STUB_DB_FILE = os.path.join(os.path.dirname(__file__), "stub_db.json")

def _json_serial(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)

def _restore_datetime(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            obj[k] = _restore_datetime(v)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            obj[i] = _restore_datetime(v)
    elif isinstance(obj, str):
        try:
            if len(obj) >= 19 and "T" in obj:
                return datetime.fromisoformat(obj)
        except ValueError:
            pass
    return obj

def load_db():
    if not os.path.exists(STUB_DB_FILE):
        return {}
    try:
        with open(STUB_DB_FILE, "r") as f:
            return _restore_datetime(json.load(f))
    except Exception:
        return {}

def save_db(data):
    with open(STUB_DB_FILE, "w") as f:
        json.dump(data, f, default=_json_serial, indent=2)

class MockCursor:
    def __init__(self, data):
        self._data = data
        self._idx = 0

    def __iter__(self):
        return self
    
    def __next__(self):
        if self._idx < len(self._data):
            val = self._data[self._idx]
            self._idx += 1
            return val
        raise StopIteration
        
    def limit(self, l):
        self._data = self._data[:l]
        return self

    def sort(self, *args, **kwargs):
        # Mocks sorting by not doing it, or just return self
        return self

class MockCollection:
    def __init__(self, name):
        self.name = name

    def _get_data(self):
        db = load_db()
        return db.get(self.name, [])

    def _save_data(self, data):
        db = load_db()
        db[self.name] = data
        save_db(db)

    def _matches(self, doc, query):
        if not query:
            return True
        for k, v in query.items():
            if "$" in k: # Skip complex MongoDB queries for the stub, or implement subset
                continue
                
            doc_val = doc.get(k)
            if isinstance(v, dict):
                matched = True
                for op, op_val in v.items():
                    if op == "$gte":
                        val_to_compare = doc_val
                        if isinstance(doc_val, str) and "T" in doc_val:
                            try:
                                val_to_compare = datetime.fromisoformat(doc_val)
                            except ValueError:
                                pass
                        
                        op_val_compare = op_val
                        if isinstance(op_val, str) and "T" in op_val:
                            try:
                                op_val_compare = datetime.fromisoformat(op_val)
                            except ValueError:
                                pass
                        
                        try:
                            if not (val_to_compare >= op_val_compare):
                                matched = False
                        except Exception:
                            matched = False
                if not matched:
                    return False
                continue

            # For JSON serialization reasons, compare strings if not exact type
            if str(doc_val) != str(v) and doc_val != v:
                return False
        return True

    def find_one(self, query=None):
        data = self._get_data()
        for doc in data:
            if self._matches(doc, query):
                return doc
        return None

    def find(self, query=None, projection=None):
        data = self._get_data()
        results = [doc for doc in data if self._matches(doc, query)]
        # simplified projection
        if projection:
            simplified = []
            exclude_id = projection.get("_id") == 0
            for r in results:
                proj_doc = {}
                if not exclude_id and "_id" in r:
                    proj_doc["_id"] = r["_id"]
                for pk, pv in projection.items():
                    if pk == "_id":
                        continue
                    if pv and pk in r:
                        proj_doc[pk] = r[pk]
                simplified.append(proj_doc)
            return MockCursor(simplified)
        return MockCursor(results)

    def insert_one(self, document):
        if "_id" not in document:
            document["_id"] = str(uuid.uuid4())
        # Convert datetimes to strings for the stub memory so they match loaded JSON
        # This keeps representation consistent.
        data = self._get_data()
        data.append(json.loads(json.dumps(document, default=_json_serial)))
        self._save_data(data)
        
        class InsertOneResult:
            def __init__(self, inserted_id):
                self.inserted_id = inserted_id
                
        return InsertOneResult(document["_id"])

    def update_one(self, query, update, upsert=False):
        data = self._get_data()
        modifications = update.get("$set", update)
        
        # Serialize modifications
        modifications = json.loads(json.dumps(modifications, default=_json_serial))
        
        for doc in data:
            if self._matches(doc, query):
                doc.update(modifications)
                self._save_data(data)
                
                class UpdateResult:
                    def __init__(self):
                        self.modified_count = 1
                        self.upserted_id = None
                return UpdateResult()
                
        if upsert:
            new_doc = {**query, **modifications}
            self.insert_one(new_doc)
            class UpdateResultUspert:
                def __init__(self):
                    self.modified_count = 0
                    self.upserted_id = new_doc.get("_id")
            return UpdateResultUspert()
            
        class UpdateResultZero:
            def __init__(self):
                self.modified_count = 0
                self.upserted_id = None
        return UpdateResultZero()

    def update_many(self, query, update):
        data = self._get_data()
        modifications = update.get("$set", update)
        modifications = json.loads(json.dumps(modifications, default=_json_serial))
        
        count = 0
        for doc in data:
            if self._matches(doc, query):
                doc.update(modifications)
                count += 1
                
        if count > 0:
            self._save_data(data)
            
        class UpdateResult:
            def __init__(self, count):
                self.modified_count = count
        return UpdateResult(count)

    def delete_one(self, query):
        data = self._get_data()
        for i, doc in enumerate(data):
            if self._matches(doc, query):
                del data[i]
                self._save_data(data)
                return type('DeleteResult', (), {'deleted_count': 1})()
        return type('DeleteResult', (), {'deleted_count': 0})()

    def delete_many(self, query):
        data = self._get_data()
        new_data = [doc for doc in data if not self._matches(doc, query)]
        deleted_count = len(data) - len(new_data)
        self._save_data(new_data)
        return type('DeleteResult', (), {'deleted_count': deleted_count})()

    def count_documents(self, query):
        data = self._get_data()
        return sum(1 for doc in data if self._matches(doc, query))
        
    def distinct(self, key):
        data = self._get_data()
        # simplified dot notation support 
        results = set()
        for doc in data:
            val = doc
            for part in key.split('.'):
                if isinstance(val, dict):
                    val = val.get(part)
                else:
                    val = None
                    break
            if val is not None:
                results.add(str(val))
        return list(results)

    def create_index(self, *args, **kwargs):
        pass

    def insert_many(self, documents):
        for doc in documents:
            self.insert_one(doc)
        return type('InsertManyResult', (), {'inserted_ids': [d.get("_id") for d in documents]})()

    def aggregate(self, pipeline):
        data = self._get_data()
        for step in pipeline:
            if "$group" in step:
                group_val = step["$group"]
                if "avgRating" in group_val and "$avg" in group_val["avgRating"]:
                    field = group_val["avgRating"]["$avg"].lstrip("$")
                    ratings = [d.get(field) for d in data if d.get(field) is not None]
                    avg = sum(ratings) / len(ratings) if ratings else 0
                    return [{"avgRating": avg}]
        return []

class MockDatabase:
    def __init__(self, name):
        self.name = name

    def __getitem__(self, name):
        return MockCollection(name)

    def list_collection_names(self):
        db = load_db()
        return list(db.keys())
        
    def create_collection(self, name):
        db = load_db()
        if name not in db:
            db[name] = []
            save_db(db)

    def command(self, cmd, *args, **kwargs):
        if cmd == "dbStats":
            return {
                "dataSize": 1024 * 1024,
                "storageSize": 2 * 1024 * 1024,
                "objects": 100,
                "avgObjSize": 1024
            }
        elif cmd == "collStats":
            # first argument or kwargs
            coll_name = args[0] if args else kwargs.get("collection")
            if not coll_name:
                coll_name = "chats"
            coll = self[coll_name]
            count = coll.count_documents({})
            return {
                "count": count,
                "size": count * 1024,
                "avgObjSize": 1024
            }
        return {}

class MockMongoClient:
    def __init__(self, *args, **kwargs):
        # Reset DB on init to ensure tests are isolated if needed, or leave it.
        # save_db({}) 
        self.admin = type("Admin", (), {"command": lambda x: True})()
        
    def __getitem__(self, name):
        return MockDatabase(name)
        
    def close(self):
        pass

class DictWithAttrs(dict):
    def __getattr__(self, name):
        if name in self:
            return self[name]
        raise AttributeError(name)

class MockGridFS:
    def __init__(self, *args, **kwargs):
        self.col = MockCollection("fs.files")
        
    def put(self, data, filename=None, **kwargs):
        file_id = str(uuid.uuid4())
        doc = {
            "_id": file_id,
            "filename": filename,
            "length": 100,
            "uploadDate": datetime.utcnow().isoformat()
        }
        doc.update(kwargs) # Metadata etc
        self.col.insert_one(doc)
        return file_id
        
    def find_one(self, query):
        res = self.col.find_one(query)
        return DictWithAttrs(res) if res else None
        
    def exists(self, query):
        return self.col.find_one(query) is not None
        
    def delete(self, file_id):
        self.col.delete_one({"_id": file_id})
