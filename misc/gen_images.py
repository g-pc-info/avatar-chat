"""Illustrious-XL v1.1 で、キャラの表情差分(立ち絵)を ComfyUI に生成させる。

使い方: python3 misc/gen_images.py spec.json [名前,名前,...]
  spec.json: {"outdir","prefix","checkpoint","width","height","steps","cfg","seed",
              "base","negative","variants":{"neutral":"追加タグ", ...}}
  同じseed・同じbaseで、表情のタグだけを変えて生成する(顔立ちを揃えるため)。
出力: <outdir>/<name>.png (PNGのメタデータにはワークフローが入るので、配布物には変換後のWebPを使う)
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HOST = os.environ.get("COMFY_HOST", "http://127.0.0.1:8188")  # ComfyUIのアドレス(環境変数 COMFY_HOST で変更)


def http(path, data=None):
    req = urllib.request.Request(HOST + path, data=None if data is None else json.dumps(data).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def upload(path: str) -> str:
    """ComfyUIのinputへ画像をアップロードして、ファイル名を返す(img2img用)。"""
    p = Path(path)
    boundary = "----avt" + str(int(time.time()))
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{p.name}\"\r\n"
            f"Content-Type: image/png\r\n\r\n").encode() + p.read_bytes() + (
        f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{boundary}--\r\n").encode()
    req = urllib.request.Request(HOST + "/upload/image", data=body,
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())["name"]


def workflow(spec, positive, seed, prefix, init=None, denoise=1.0):
    wf = _workflow(spec, positive, seed, prefix)
    if init:  # 基準画像を元に、表情だけ変える(顔立ち・服・リボンを保つ)
        wf["8"] = {"class_type": "LoadImage", "inputs": {"image": init}}
        wf["9"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["8", 0], "vae": ["1", 2]}}
        wf["5"]["inputs"]["latent_image"] = ["9", 0]
        wf["5"]["inputs"]["denoise"] = denoise
    return wf


def _workflow(spec, positive, seed, prefix):
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": spec["checkpoint"]}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": spec["negative"], "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage",
              "inputs": {"width": spec["width"], "height": spec["height"], "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {
            "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0],
            "seed": seed, "steps": spec.get("steps", 28), "cfg": spec.get("cfg", 5.5),
            "sampler_name": "euler_ancestral", "scheduler": "normal", "denoise": 1.0}},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": prefix}},
    }


def generate(spec, name, tags, out):
    positive = spec["base"] + ", " + tags
    prefix = f"{spec['prefix']}_{name}"
    init = upload(spec["init_image"]) if spec.get("init_image") else None
    denoise = spec.get("variant_denoise", {}).get(name, spec.get("denoise", 1.0))
    resp = json.loads(http("/prompt", {"prompt": workflow(spec, positive, spec["seed"], prefix, init, denoise)}))
    pid = resp["prompt_id"]
    print(f"[{name}] prompt_id={pid}", flush=True)
    t0 = time.time()
    while time.time() - t0 < 300:
        q = json.loads(http("/queue"))
        ids = [j[1] for j in q["queue_running"]] + [j[1] for j in q["queue_pending"]]
        if pid not in ids:
            break
        time.sleep(3)
    hist = {}
    for _ in range(10):
        hist = json.loads(http(f"/history/{pid}"))
        if pid in hist:
            break
        time.sleep(5)
    if pid not in hist:
        raise RuntimeError(f"history not found for {pid}")
    files = [i for n in hist[pid]["outputs"].values() for i in n.get("images", [])]
    if len(files) != 1:
        raise RuntimeError(f"expected 1 image, got {files}")
    f = files[0]
    data = http(f"/view?filename={f['filename']}&subfolder={f.get('subfolder', '')}&type={f['type']}")
    (out / f"{name}.png").write_bytes(data)
    print(f"[{name}] saved {f['filename']} ({len(data)} bytes, {time.time() - t0:.0f}s)", flush=True)


def main():
    spec = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    only = sys.argv[2].split(",") if len(sys.argv) > 2 else list(spec["variants"])
    out = Path(spec["outdir"])
    out.mkdir(parents=True, exist_ok=True)
    for name in only:
        generate(spec, name, spec["variants"][name], out)


if __name__ == "__main__":
    main()
