/* The clinical UI sends its existing requests to a Python worker in this tab. */
(() => {
  const pending = new Map();
  const status = document.getElementById("localStatus");
  const fetchStatic = window.fetch.bind(window);
  let worker;
  let nextId = 0;

  function startupError(error) {
    console.error(error);
    worker?.terminate();
    worker = undefined;
    const link = document.createElement("a");
    link.href = "./browser.html";
    link.textContent = "Mở bản web nhẹ";
    status.replaceChildren("Không tải được chương trình. Hãy tải lại trang hoặc ", link, ".");
    status.hidden = false;
    for (const resolve of pending.values()) {
      resolve(Response.json({ok: false, msg: "Chương trình trên trình duyệt chưa sẵn sàng."}, {status: 503}));
    }
    pending.clear();
  }

  function start() {
    status.textContent = "Đang tải chương trình Python…";
    status.hidden = false;
    worker = new Worker("./worker.mjs", {type: "module"});
    worker.addEventListener("error", startupError);
    worker.addEventListener("messageerror", startupError);
    worker.addEventListener("message", ({data}) => {
      if (data.startupError) {
        startupError(data.startupError);
        return;
      }
      if (data.ready) {
        status.hidden = data.persistent;
        if (!data.persistent) status.textContent = "Trình duyệt chỉ lưu dữ liệu trong tab này. Hãy tải báo cáo trước khi đóng tab.";
        return;
      }
      const resolve = pending.get(data.id);
      if (!resolve) return;
      pending.delete(data.id);
      resolve(new Response(data.body, {status: data.status, headers: data.headers}));
    });
  }

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
    if (!worker) start();
    return new Promise(resolve => {
      const id = ++nextId;
      pending.set(id, resolve);
      worker.postMessage({
        id, method: request.method, path: url.pathname + url.search,
        contentType: request.headers.get("content-type"), body,
      }, [body]);
    });
  };

  window.pharmaDeskLocal = {
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
