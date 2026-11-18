/* The clinical UI sends its existing requests to a Python worker in this tab. */
(() => {
  const pending = new Map();
  const status = document.getElementById("localStatus");
  const message = document.getElementById("localStatusMessage");
  const retry = document.getElementById("localRetry");
  const fetchStatic = window.fetch.bind(window);
  const startupTimeout = 90_000;
  let worker;
  let startupTimer;
  let nextId = 0;
  const cacheReady = prepareCache();

  async function prepareCache() {
    const serviceWorkers = navigator.serviceWorker;
    if (!serviceWorkers) return;
    const registration = serviceWorkers.register("./runtime-cache.js").catch(() => null);
    if (serviceWorkers.controller) return;
    await new Promise(resolve => {
      const finish = () => {
        clearTimeout(timer);
        serviceWorkers.removeEventListener("controllerchange", finish);
        resolve();
      };
      const timer = setTimeout(finish, 1800);
      serviceWorkers.addEventListener("controllerchange", finish);
      registration.then(result => {
        if (!result || serviceWorkers.controller) finish();
      });
    });
  }

  function startupError(failedWorker, error) {
    if (worker !== failedWorker) return;
    console.error(error);
    clearTimeout(startupTimer);
    worker?.terminate();
    worker = undefined;
    message.textContent = "Chưa khởi động được chương trình. Bấm Thử lại để tiếp tục.";
    status.hidden = false;
    retry.hidden = false;
    for (const resolve of pending.values()) {
      resolve(Response.json({ok: false, msg: "Chương trình trên trình duyệt chưa sẵn sàng."}, {status: 503}));
    }
    pending.clear();
  }

  function start() {
    message.textContent = "Đang chuẩn bị xử lý trên thiết bị…";
    status.hidden = false;
    retry.hidden = true;
    const running = new Worker("./worker.mjs?v=__WORKER_VERSION__", {type: "module"});
    worker = running;
    startupTimer = setTimeout(() => startupError(running, new Error("Python startup timed out")), startupTimeout);
    running.addEventListener("error", error => startupError(running, error));
    running.addEventListener("messageerror", error => startupError(running, error));
    running.addEventListener("message", ({data}) => {
      if (worker !== running) return;
      if (data.startupError) {
        startupError(running, data.startupError);
        return;
      }
      if (data.ready) {
        clearTimeout(startupTimer);
        status.hidden = data.persistent;
        if (!data.persistent) message.textContent = "Trình duyệt chỉ lưu dữ liệu trong tab này. Hãy tải báo cáo trước khi đóng tab.";
        return;
      }
      const resolve = pending.get(data.id);
      if (!resolve) return;
      pending.delete(data.id);
      resolve(new Response(data.body, {status: data.status, headers: data.headers}));
    });
  }

  retry.addEventListener("click", async () => {
    const active = document.querySelector('.tab[aria-current="page"]');
    if (active?.id === "tabTdm") tdmCalc();
    else active?.click();
    const response = await window.fetch("/api/version");
    if (response.ok) document.getElementById("ver").textContent = "· " + (await response.json()).v;
  });

  window.fetch = async (input, options) => {
    const request = new Request(input, options);
    const url = new URL(request.url);
    if (url.origin !== location.origin || !url.pathname.startsWith("/api/")) {
      return fetchStatic(request);
    }
    const body = request.body ? await request.arrayBuffer() : new ArrayBuffer(0);
    if (body.byteLength > 20 * 1024 * 1024) {
      return Response.json({ok: false, msg: "Yêu cầu vượt giới hạn 20 MB."}, {status: 413});
    }
    if (!worker) await cacheReady;
    return new Promise(resolve => {
      const id = ++nextId;
      pending.set(id, resolve);
      if (!worker) {
        try {
          start();
        } catch (error) {
          startupError(worker, error);
          return;
        }
      }
      worker.postMessage({
        id, method: request.method, path: url.pathname + url.search,
        contentType: request.headers.get("content-type"), body,
      }, [body]);
    });
  };

  window.pharmaDeskLocal = {
    abcFields: __ABC_FIELDS__,
    async download(url, name) {
      const response = await window.fetch(url);
      if (!response.ok) throw new Error((await response.json()).msg);
      const href = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = href;
      link.download = name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(href), 1000);
    },
  };
})();
