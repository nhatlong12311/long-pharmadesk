// Share Pyodide's IDBFS entries and lock so existing drafts and open tabs keep working.
const mount = "/pharmadesk-data";
const adr = mount + "/ADR";
const directory = adr + "/Ban_nhap";
const prefix = directory + "/";
const files = "FILE_DATA";
const memory = new Map();
const encoder = new TextEncoder();
const decoder = new TextDecoder();
const draftName = /^[a-zA-Z0-9_-]{1,96}$/;
const date = new Intl.DateTimeFormat("en-GB", {day:"2-digit", month:"2-digit", year:"numeric"});
const time = new Intl.DateTimeFormat("en-GB", {hour:"2-digit", minute:"2-digit", hourCycle:"h23"});
const actions = new Map([
  ["GET /api/adr/state", state],
  ["GET /api/adr/drafts", list],
  ["GET /api/adr/draft", load],
  ["POST /api/adr/draft", save],
  ["POST /api/adr/draft/delete", remove],
]);
let database;

function openDatabase() {
  if (!navigator.locks || !globalThis.indexedDB) return Promise.resolve(null);
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(mount, 21);
    request.onupgradeneeded = () => {
      const store = request.result.objectStoreNames.contains(files)
        ? request.transaction.objectStore(files) : request.result.createObjectStore(files);
      if (!store.indexNames.contains("timestamp")) store.createIndex("timestamp", "timestamp");
    };
    request.onsuccess = () => {
      const db = request.result;
      db.onversionchange = () => { db.close(); database = undefined; };
      resolve(db);
    };
    request.onerror = () => reject(request.error);
  });
}

function result(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function withStore(mode, action) {
  database ??= openDatabase().catch(() => null);
  const db = await database;
  if (!db) return action(null);
  return navigator.locks.request("pharmadesk-local-storage", async () => {
    const tx = db.transaction(files, mode);
    const done = new Promise((resolve, reject) => {
      tx.oncomplete = resolve;
      tx.onabort = () => reject(tx.error);
    });
    const [value] = await Promise.all([action(tx.objectStore(files)), done]);
    return value;
  });
}

function readJson(entry) {
  try {
    const value = JSON.parse(decoder.decode(entry?.contents));
    if (isObject(value)) return value;
  } catch {
    // Unreadable legacy entries are left in place.
  }
}

const stateFile = /^(ABCVEN\/(hoat_chat_theo_doi\.json|Lich_su\/(1999|20\d\d|2100)-(0[1-9]|1[0-2])\.json)|TuongTac\/Quy_tac_tuong_tac\.json)$/;

export async function readStateFiles(keys) {
  return withStore("readonly", async store => {
    const entries = await Promise.all(keys.filter(key => stateFile.test(key)).map(async key => {
      const entry = await get(store, mount + "/" + key);
      try { return [key, JSON.parse(decoder.decode(entry?.contents))]; }
      catch { return [key, undefined]; }
    }));
    return Object.fromEntries(entries.filter(([, value]) => value !== undefined));
  });
}

export async function writeStateFiles(values) {
  return withStore("readwrite", async store => {
    for (const [file, value] of Object.entries(values)) {
      if (!stateFile.test(file)) continue;
      const key = mount + "/" + file;
      if (value === null) await deleteEntry(store, key);
      else await writeEntry(store, key, value);
    }
  });
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function get(store, key) {
  return store ? result(store.get(key)) : memory.get(key);
}

async function state() {
  return withStore("readonly", async store => ({
    defaults: readJson(await get(store, adr + "/adr_defaults.json")) ?? {},
    today: date.format(new Date()),
    template: true,
    font: true,
    persistent: Boolean(store),
  }));
}

async function list() {
  return withStore("readonly", async store => {
    const range = store && IDBKeyRange.bound(prefix, prefix + "\uffff");
    const [keys, entries] = store
      ? await Promise.all([result(store.getAllKeys(range)), result(store.getAll(range))])
      : [[...memory.keys()], [...memory.values()]];
    const drafts = [];
    keys.forEach((key, index) => {
      const name = key.slice(prefix.length, -5);
      const entry = entries[index];
      if (!key.startsWith(prefix) || !key.endsWith(".json") || !draftName.test(name)) return;
      const value = readJson(entry);
      if (!value || !(entry.timestamp instanceof Date)) return;
      drafts.push({
        name, ten_bn: String(value.ten_bn ?? "").trim(), timestamp: entry.timestamp,
        saved: date.format(entry.timestamp) + " " + time.format(entry.timestamp),
      });
    });
    drafts.sort((a, b) => b.timestamp - a.timestamp);
    return {drafts: drafts.map(({name, ten_bn, saved}) => ({name, ten_bn, saved}))};
  });
}

async function load(url) {
  const name = url.searchParams.get("name");
  if (typeof name !== "string" || !draftName.test(name)) return badName();
  return withStore("readonly", async store => {
    const data = readJson(await get(store, prefix + name + ".json"));
    return data ? {ok:true, data} : {ok:false, msg:"Không thấy bản nháp."};
  });
}

async function save(_url, payload) {
  const data = payload.data ?? {};
  if (!isObject(data)) return {ok:false, msg:"Dữ liệu bản nháp phải là một đối tượng."};
  const name = payload.name || crypto.randomUUID().replaceAll("-", "");
  if (typeof name !== "string" || !draftName.test(name)) return badName();
  await withStore("readwrite", store => writeEntry(store, prefix + name + ".json", data));
  return {ok:true, name};
}

async function writeEntry(store, key, data) {
  const previous = await get(store, key);
  const timestamp = new Date(Math.max(Date.now(), Number(previous?.timestamp ?? 0) + 1));
  const entry = {timestamp, mode:0o100644, contents:encoder.encode(JSON.stringify(data))};
  if (!store) {
    memory.set(key, entry);
    return;
  }
  const parts = key.slice(mount.length + 1).split("/").slice(0, -1);
  let folder = mount;
  for (const part of parts) {
    folder += "/" + part;
    if (!await get(store, folder)) store.put({timestamp, mode:0o40755}, folder);
  }
  await result(store.put(entry, key));
}

function deleteEntry(store, key) {
  return store ? result(store.delete(key)) : memory.delete(key);
}

async function remove(_url, payload) {
  const name = payload.name;
  if (typeof name !== "string" || !draftName.test(name)) return badName();
  await withStore("readwrite", store => deleteEntry(store, prefix + name + ".json"));
  return {ok:true};
}

function badName() {
  return {ok:false, msg:"Mã bản nháp không hợp lệ."};
}

export async function handleAdrRequest(method, url, body) {
  const action = actions.get(method + " " + url.pathname);
  if (!action) return null;
  let payload = {};
  if (method === "POST") {
    try { payload = JSON.parse(decoder.decode(body)); } catch { payload = null; }
    if (!isObject(payload)) {
      return Response.json({ok:false, msg:"Nội dung yêu cầu phải là một đối tượng JSON."}, {status:400});
    }
  }
  try {
    return Response.json(await action(url, payload));
  } catch (error) {
    console.warn(error);
    return Response.json({ok:false, msg:"Không truy cập được bản nháp trên thiết bị."}, {status:503});
  }
}
