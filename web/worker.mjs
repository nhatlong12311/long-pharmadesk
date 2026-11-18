const runtime = new URL("./runtime/__RUNTIME_VERSION__/", import.meta.url);
const sourceFile = new URL("./__PYTHON_SOURCE__", import.meta.url);
const dataPath = "/pharmadesk-data";
const storageLock = "pharmadesk-local-storage";
const noBody = [204, 205, 304];
const framework = ["blinker", "click", "flask", "itsdangerous", "jinja2", "markupsafe", "werkzeug"];
const excel = ["et_xmlfile", "lxml", "openpyxl", "xlrd"];
const word = ["lxml", "python_docx", "typing-extensions"];
const adrReports = [...word, "charset_normalizer", "pillow", "pypdf", "reportlab"];

function reportPackages(method, path) {
  if (method === "POST" && path === "/api/adr/generate") return adrReports;
  if (path === "/api/ttt/state") return excel;
  if (method !== "POST") return [];
  if (["/api/abc/generate", "/api/abc/generate-four", "/api/ttt/generate"].includes(path)) {
    return [...new Set([...excel, ...word])];
  }
  if (path === "/api/ttt/inspect" || (path.startsWith("/api/abc/") && path !== "/api/abc/watch")) {
    return excel;
  }
  return [];
}

async function getAsset(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Không tải được ${url.pathname} · HTTP ${response.status}`);
  return response;
}

async function initialize() {
  const [py, packages, source] = await Promise.all([
    import(new URL("pyodide.mjs", runtime)).then(({loadPyodide}) => loadPyodide({indexURL: runtime.href})),
    getAsset(new URL("wheels.json", runtime)).then(response => response.json()),
    getAsset(sourceFile).then(response => response.arrayBuffer()),
  ]);
  const wheelUrls = new Map(packages.pure.map(file => [file.split("-")[0], new URL("wheels/" + file, runtime).href]));
  const loaded = new Set();
  async function loadPackages(names) {
    const missing = names.filter(name => !loaded.has(name));
    if (!missing.length) return;
    let installFailed = false;
    await py.loadPackage(missing.map(name => wheelUrls.get(name) ?? name), {
      errorCallback: error => {
        installFailed = true;
        console.error(error);
      },
    });
    if (installFailed) throw new Error("Không tải được thư viện Python cho thao tác này.");
    for (const name of missing) loaded.add(name);
  }
  await loadPackages(framework);
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
  return {backend, persistent, syncFiles, loadPackages};
}

const started = initialize();
let queue = Promise.resolve();
started.catch(error => postMessage({startupError: String(error)}));

async function dispatch(message) {
  const {backend, persistent, syncFiles, loadPackages} = await started;
  await loadPackages(reportPackages(message.method, message.path.split("?")[0]));
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
