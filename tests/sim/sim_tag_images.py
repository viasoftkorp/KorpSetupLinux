#!/usr/bin/env python3
"""Isolated-test helper: make every private app image referenced by the repo's compose templates
(or by rendered compose files) resolvable locally by tagging the fake image, so the real playbook
can run `docker compose up` without registry credentials. Public infra images are left alone
(pulled for real), except the ones in FAKE_PUBLIC that must not run for real in a sandbox."""
import glob, os, re, subprocess, sys, time
import jinja2

ACCOUNT = os.environ.get("SIM_ACCOUNT", "korpsim")
FAKE_PUBLIC = ("nickfedor/watchtower", "portainer/portainer-ce", "sosedoff/pgweb")
IMG_RE = re.compile(r'^\s*image:\s*["\']?([^"\'\s#]+)', re.M)

def local_images():
    out = subprocess.run(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}"],
                         capture_output=True, text=True).stdout
    return set(out.split())

def wanted(img):
    return img.startswith(ACCOUNT + "/") or img.startswith(FAKE_PUBLIC)

def tag(images):
    have = local_images()
    n = 0
    for img in sorted(images):
        if wanted(img) and img not in have and "{" not in img and "$" not in img:
            subprocess.run(["docker", "tag", "korpsim-fake:latest", img], check=True)
            n += 1
    return n

def from_templates(repo, versions):
    env = jinja2.Environment(undefined=jinja2.ChainableUndefined)
    imgs = set()
    for path in glob.glob(f"{repo}/roles/*/templates/composes/**/*.j2", recursive=True):
        src = open(path).read()
        for v in versions:
            try:
                txt = env.from_string(src).render(docker_account=ACCOUNT, docker_image_suffix="",
                                                  version_without_build=v)
            except Exception:
                txt = src
            imgs.update(IMG_RE.findall(txt))
    return imgs

def from_rendered():
    imgs = set()
    for path in glob.glob("/etc/korp/composes/**/*.yml", recursive=True):
        try:
            imgs.update(IMG_RE.findall(open(path).read()))
        except OSError:
            pass
    return imgs

if __name__ == "__main__":
    if sys.argv[1] == "templates":
        print("tagged", tag(from_templates(sys.argv[2], sys.argv[3].split(","))))
    elif sys.argv[1] == "public":
        imgs = set()
        for d in glob.glob(sys.argv[2] + "/**/roles", recursive=True):
            imgs |= from_templates(os.path.dirname(d), sys.argv[3].split(","))
        for i in sorted(imgs):
            if not wanted(i) and "{" not in i and "$" not in i and i != "korpsim-fake:latest":
                print(i)
    elif sys.argv[1] == "watch":
        while True:
            tag(from_rendered())
            time.sleep(0.3)
