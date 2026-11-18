import { loadPyodide } from "./runtime/pyodide.mjs";

const runtime = new URL("./runtime/", import.meta.url);
const dataPath = "/pharmadesk-data";
const storageLock = "pharmadesk-local-storage";
const noBody = [204, 205, 304];

async function getAsset(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Không tải được ${url.pathname} · HTTP ${response.status}`);
  return response;
}

async function initialize() {
  const [py, packages, source] = await Promise.all([
    loadPyodide({indexURL: runtime.href}),
    getAsset(new URL("wheels.json", runtime)).then(response => response.json()),
    getAsset(new URL("./python.zip", import.meta.url)).then(response => response.arrayBuffer()),
  ]);
  await py.loadPackage([...packages.wasm, ...packages.pure.map(name => new URL("wheels/" + name, runtime).href)]);
  py.unpackArchive(source, "zip", {extractDir: "/pharmadesk"});
  py.FS.mkdir(dataPath);
  const syncFiles = populate => new Promise((resolve, reject) => {
    py.FS.syncfs(populate, error => error ? reject(error) : resolve());
  });
  const importBackend = () => py.runPython("import sys; sys.path.insert(0, '/pharmadesk'); from browser_backend import handle_request");

  // Sync under a browser lock so updates made in another tab aren't lost.
  let persistent = false;
  if (navigator.locks && py.FS.filesystems.IDBFS) {
    await navigator.locks.request(storageLock, async () => {
      py.FS.mount(py.FS.filesystems.IDBFS, {}, dataPath);
      try {
        await syncFiles(true);
        persistent = true;
      } catch (error) {
        console.warn(error);
        py.FS.unmount(dataPath);
      }
      importBackend();
      if (persistent) await syncFiles(false);
    });
  } else {
    importBackend();
  }
  const backend = py.globals.get("handle_request");
  postMessage({ready: true, persistent});
  return {backend, persistent, syncFiles};
}

const started = initialize();
let queue = Promise.resolve();
started.catch(error => postMessage({startupError: String(error)}));

async function dispatch(message) {
  const {backend, persistent, syncFiles} = await started;
  const run = async () => {
    if (persistent) await syncFiles(true);
    const result = backend(message.method, message.path, message.contentType, new Uint8Array(message.body));
    try {
      const [status, headers, body] = result.toJs();
      if (persistent && message.method !== "GET" && message.method !== "HEAD") await syncFiles(false);
      const content = noBody.includes(status) || message.method === "HEAD" ? null : body;
      postMessage({id: message.id, status, headers, body: content}, content ? [content.buffer] : []);
    } finally {
      result.destroy();
    }
  };
  if (persistent) await navigator.locks.request(storageLock, run);
  else await run();
}

self.addEventListener("message", ({data}) => {
  queue = queue.then(() => dispatch(data)).catch(error => {
    console.error(error);
    const body = new TextEncoder().encode(JSON.stringify({ok: false, msg: "Không xử lý được yêu cầu trên thiết bị."}));
    postMessage({id: data.id, status: 500, headers: [["Content-Type", "application/json"]], body}, [body.buffer]);
  });
});
