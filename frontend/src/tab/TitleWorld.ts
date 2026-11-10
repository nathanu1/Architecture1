import * as THREE from "three";
import { TextGeometry } from "three/examples/jsm/geometries/TextGeometry.js";
import { Font } from "three/examples/jsm/loaders/FontLoader.js";
import { buildResident } from "../scene/meshes";
import type { Look } from "../types";
import fontData from "./title-font.json";

// The title screen as a small world at dusk: the town's name in chunky letters standing on warm
// ground, grass, blossom and autumn trees, lanterns, a cottage, a river behind, and the three
// neighbours. Everything is built here from boxes, cones and blobs; nothing is loaded.

const C = {
  sky: "#f4a08c",
  ground: "#f08a80",
  path: "#f6a596",
  tile: "#e97f78",
  grassDark: "#8a7426",
  grassLight: "#cdb04a",
  letters: "#dfa6ff",
  water: "#6b62cc",
  waterLight: "#9d8ff0",
  bank: "#d9705c",
  trunk: "#7a4db0",
  blossom: ["#f25f9f", "#ff8cc0", "#ffb3d6"],
  autumn: ["#f2a13a", "#e8683c", "#ffc85a"],
  post: "#5a3d9e",
  glow: "#ffd24a",
  wall: "#ffe6d2",
  roof: "#d63a58",
  wood: "#c9573f",
  rock: "#c8a2ea",
};

const NEIGHBOURS: Look[] = [
  { shirt: "#3BA7A0", pants: "#3D4A63", hair: "#2B1D1A", hair_style: "long", skin: "#C98E6A", accessory: "headphones" },
  { shirt: "#E8735F", pants: "#5B4B6B", hair: "#3A2522", hair_style: "bun", skin: "#D9A57E", accessory: "apron" },
  { shirt: "#7BAF6E", pants: "#4A5568", hair: "#E2C27A", hair_style: "short", skin: "#F2CDB0", accessory: "glasses" },
];

/** A small repeatable random source, so the world looks the same on every visit. */
function seeded(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const easeOutBounce = (x: number): number => {
  const n = 7.5625;
  const d = 2.75;
  if (x < 1 / d) return n * x * x;
  if (x < 2 / d) return n * (x -= 1.5 / d) * x + 0.75;
  if (x < 2.5 / d) return n * (x -= 2.25 / d) * x + 0.9375;
  return n * (x -= 2.625 / d) * x + 0.984375;
};

export class TitleWorld {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(32, 1, 0.1, 200);
  private owned: { dispose(): void }[] = [];
  private letters: { mesh: THREE.Mesh; delay: number }[] = [];
  private figures: THREE.Group[] = [];
  private glows: THREE.PointLight[] = [];
  private streaks: THREE.Mesh[] = [];
  private pointer = new THREE.Vector2();
  private eased = new THREE.Vector2();
  private home = new THREE.Vector3();
  private look = new THREE.Vector3();
  private frame = 0;
  private started = performance.now();
  private portrait = false;
  private observer: ResizeObserver;

  constructor(
    private canvas: HTMLCanvasElement,
    private reduce: boolean,
  ) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.scene.background = new THREE.Color(C.sky);
    this.scene.fog = new THREE.Fog(C.sky, 26, 58);
    this.light();
    this.land();
    this.river();
    this.grass();
    this.props();
    this.word();
    this.people();
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(canvas);
    window.addEventListener("pointermove", this.onPointer, { passive: true });
    document.addEventListener("visibilitychange", this.onVisibility);
    this.resize();
    this.tick();
  }

  // ------------------------------------------------------------------ building blocks
  private keep<T extends { dispose(): void }>(x: T): T {
    this.owned.push(x);
    return x;
  }

  private mat(color: string, opts: { emissive?: string; flat?: boolean } = {}): THREE.MeshLambertMaterial {
    return this.keep(new THREE.MeshLambertMaterial({ color, flatShading: opts.flat ?? false, emissive: opts.emissive ?? "#000000", emissiveIntensity: opts.emissive ? 1 : 0 }));
  }

  private add(geometry: THREE.BufferGeometry, material: THREE.Material, x: number, y: number, z: number, parent: THREE.Object3D = this.scene): THREE.Mesh {
    const m = new THREE.Mesh(this.keep(geometry), material);
    m.position.set(x, y, z);
    m.castShadow = true;
    m.receiveShadow = true;
    parent.add(m);
    return m;
  }

  private light(): void {
    this.scene.add(new THREE.HemisphereLight("#ffd3d9", "#7d55ea", 1.45));
    this.scene.add(new THREE.AmbientLight("#c66bff", 0.3));
    const sun = new THREE.DirectionalLight("#ffd2b0", 2.1);
    sun.position.set(-8, 12, -3);
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.camera.left = -18;
    sun.shadow.camera.right = 18;
    sun.shadow.camera.top = 16;
    sun.shadow.camera.bottom = -16;
    sun.shadow.camera.far = 50;
    sun.shadow.bias = -0.0006;
    sun.shadow.normalBias = 0.03;
    this.scene.add(sun);
  }

  private land(): void {
    const ground = this.add(new THREE.CircleGeometry(70, 48), this.mat(C.ground), 0, 0, 0);
    ground.rotation.x = -Math.PI / 2;
    ground.castShadow = false;
    // paving: a few rows of slightly darker tiles under the word, like a town square
    const tile = this.mat(C.tile);
    const paving = new THREE.InstancedMesh(this.keep(new THREE.BoxGeometry(0.92, 0.02, 0.92)), tile, 240);
    const m = new THREE.Matrix4();
    let n = 0;
    for (let ix = -10; ix < 10; ix++) for (let iz = -3; iz < 9; iz++) paving.setMatrixAt(n++, m.makeTranslation(ix + 0.5, 0.005, iz + 0.5));
    paving.receiveShadow = true;
    paving.rotation.y = 0.14;
    this.scene.add(paving);
    const patch = this.add(new THREE.CircleGeometry(5.2, 40), this.mat(C.path), 5.5, 0.012, 5.5);
    patch.rotation.x = -Math.PI / 2;
    patch.castShadow = false;
  }

  private river(): void {
    const water = this.add(new THREE.PlaneGeometry(90, 9), this.keep(new THREE.MeshBasicMaterial({ color: C.water })), 0, 0.03, -11.9);
    water.rotation.x = -Math.PI / 2;
    water.castShadow = false;
    const bank = this.add(new THREE.BoxGeometry(90, 0.16, 0.5), this.mat(C.bank), 0, 0.08, -7.3);
    bank.castShadow = false;
    const far = this.add(new THREE.BoxGeometry(90, 0.16, 0.5), this.mat(C.bank), 0, 0.08, -16.5);
    far.castShadow = false;
    const streak = this.keep(new THREE.MeshBasicMaterial({ color: C.waterLight, transparent: true, opacity: 0.75 }));
    const rnd = seeded(7);
    for (let i = 0; i < 16; i++) {
      const s = this.add(new THREE.PlaneGeometry(1.6 + rnd() * 2.6, 0.07), streak, -30 + rnd() * 60, 0.045, -15.6 + rnd() * 7);
      s.rotation.x = -Math.PI / 2;
      s.castShadow = false;
      s.userData.phase = rnd() * 6.28;
      this.streaks.push(s);
    }
    // a little wooden bridge
    const wood = this.mat(C.wood);
    const bridge = new THREE.Group();
    this.add(new THREE.BoxGeometry(3, 0.18, 10), wood, 0, 0.32, 0, bridge);
    for (const side of [-1.45, 1.45]) {
      this.add(new THREE.BoxGeometry(0.14, 0.14, 10), wood, side, 1.05, 0, bridge);
      for (let k = -4.5; k <= 4.5; k += 1.5) this.add(new THREE.BoxGeometry(0.16, 0.9, 0.16), wood, side, 0.7, k, bridge);
    }
    bridge.position.set(-11.5, 0, -11.9);
    this.scene.add(bridge);
  }

  private grass(): void {
    const tuft = new THREE.ConeGeometry(0.11, 0.46, 4);
    tuft.translate(0, 0.23, 0);
    const colors: number[] = [];
    const dark = new THREE.Color(C.grassDark);
    const light = new THREE.Color(C.grassLight);
    const pos = tuft.getAttribute("position");
    for (let i = 0; i < pos.count; i++) {
      const c = dark.clone().lerp(light, Math.min(1, pos.getY(i) / 0.46));
      colors.push(c.r, c.g, c.b);
    }
    tuft.setAttribute("color", new THREE.Float32BufferAttribute(colors, 3));
    const patches: [number, number, number][] = [
      [-11.5, 2.5, 3.6],
      [-3.5, -5.2, 4.2],
      [4.6, -5.6, 3.4],
      [11.5, -3.6, 4.2],
      [13.5, 6.5, 3.6],
      [3.5, 10.5, 4.2],
      [-12, 11, 4.4],
      [-16, -4.5, 3.4],
    ];
    const rnd = seeded(3);
    const spots: THREE.Matrix4[] = [];
    const q = new THREE.Quaternion();
    const up = new THREE.Vector3(0, 1, 0);
    for (const [cx, cz, r] of patches) {
      const blob = this.add(new THREE.CircleGeometry(r * 0.98, 28), this.mat(C.grassDark), cx, 0.014, cz);
      blob.rotation.x = -Math.PI / 2;
      blob.castShadow = false;
      const count = Math.round(r * r * 60);
      for (let i = 0; i < count; i++) {
        const a = rnd() * Math.PI * 2;
        const d = Math.sqrt(rnd()) * r;
        const s = 0.7 + rnd() * 0.8;
        q.setFromAxisAngle(up, rnd() * Math.PI);
        spots.push(new THREE.Matrix4().compose(new THREE.Vector3(cx + Math.cos(a) * d, 0, cz + Math.sin(a) * d), q.clone(), new THREE.Vector3(s, s * (0.8 + rnd() * 0.6), s)));
      }
    }
    const field = new THREE.InstancedMesh(this.keep(tuft), this.keep(new THREE.MeshLambertMaterial({ vertexColors: true, flatShading: true })), spots.length);
    spots.forEach((mx, i) => field.setMatrixAt(i, mx));
    field.receiveShadow = true;
    this.scene.add(field);
  }

  private tree(x: number, z: number, palette: string[], scale: number, seed: number): void {
    const rnd = seeded(seed);
    const g = new THREE.Group();
    this.add(new THREE.CylinderGeometry(0.16, 0.24, 2.4, 7), this.mat(C.trunk, { flat: true }), 0, 1.2, 0, g);
    const mats = palette.map((c) => this.mat(c, { flat: true }));
    for (let i = 0; i < 9; i++) {
      const r = 0.7 + rnd() * 0.7;
      const blob = this.add(new THREE.IcosahedronGeometry(r, 0), mats[i % mats.length], (rnd() - 0.5) * 2.2, 2.6 + rnd() * 1.4, (rnd() - 0.5) * 2.2, g);
      blob.rotation.set(rnd() * 3, rnd() * 3, rnd() * 3);
    }
    g.position.set(x, 0, z);
    g.scale.setScalar(scale);
    this.scene.add(g);
  }

  private lantern(x: number, z: number, tall: boolean): void {
    const g = new THREE.Group();
    const post = this.mat(C.post);
    const h = tall ? 2.1 : 0.5;
    this.add(new THREE.BoxGeometry(0.2, h, 0.2), post, 0, h / 2, 0, g);
    this.add(new THREE.BoxGeometry(0.62, 0.12, 0.62), post, 0, h + 0.06, 0, g);
    const glass = this.add(new THREE.BoxGeometry(0.46, 0.5, 0.46), this.mat(C.glow, { emissive: C.glow }), 0, h + 0.37, 0, g);
    glass.castShadow = false;
    const cap = this.add(new THREE.ConeGeometry(0.5, 0.34, 4), post, 0, h + 0.79, 0, g);
    cap.rotation.y = Math.PI / 4;
    const lamp = new THREE.PointLight("#ffc04a", 9, 7, 2);
    lamp.position.set(0, h + 0.4, 0);
    g.add(lamp);
    this.glows.push(lamp);
    g.position.set(x, 0, z);
    this.scene.add(g);
  }

  private props(): void {
    this.tree(-2.2, -5.4, C.blossom, 1.25, 11);
    this.tree(4.4, -6.2, C.blossom, 0.8, 12);
    this.tree(12.2, -5.6, C.autumn, 1.1, 13);
    this.tree(15.5, 1.5, C.autumn, 0.9, 14);
    this.tree(-15, -5, C.autumn, 1.05, 15);
    this.tree(-18, 6, C.blossom, 0.95, 16);
    // the far bank
    this.tree(-3, -19, C.autumn, 1.2, 17);
    this.tree(6.5, -20.5, C.blossom, 1.3, 18);
    this.tree(16, -18.5, C.autumn, 1.0, 19);
    this.tree(-19, -19.5, C.blossom, 1.1, 20);
    this.lantern(-6.4, -1.9, true);
    this.lantern(8.9, -2.6, false);
    this.lantern(-10.8, 6.2, false);

    // the cottage from the town's icon
    const house = new THREE.Group();
    this.add(new THREE.BoxGeometry(3.4, 2.2, 2.8), this.mat(C.wall), 0, 1.1, 0, house);
    const roof = this.add(new THREE.ConeGeometry(2.9, 1.7, 4), this.mat(C.roof, { flat: true }), 0, 3.05, 0, house);
    roof.rotation.y = Math.PI / 4;
    this.add(new THREE.BoxGeometry(0.5, 1.1, 0.5), this.mat(C.roof), 0.9, 3.2, -0.4, house);
    this.add(new THREE.BoxGeometry(0.7, 1.25, 0.1), this.mat(C.trunk), 0, 0.63, 1.42, house);
    for (const wx of [-1.05, 1.05]) this.add(new THREE.BoxGeometry(0.62, 0.62, 0.1), this.mat(C.glow, { emissive: C.glow }), wx, 1.35, 1.42, house).castShadow = false;
    house.position.set(9.4, 0, -5.2);
    house.rotation.y = -0.32;
    this.scene.add(house);

    // a bench, crates and a few stones
    const wood = this.mat(C.wood);
    const bench = new THREE.Group();
    this.add(new THREE.BoxGeometry(2.4, 0.14, 0.7), wood, 0, 0.55, 0, bench);
    this.add(new THREE.BoxGeometry(2.4, 0.6, 0.12), wood, 0, 1.0, -0.3, bench);
    for (const bx of [-1.05, 1.05]) this.add(new THREE.BoxGeometry(0.14, 0.55, 0.6), this.mat(C.post), bx, 0.28, 0, bench);
    bench.position.set(1.8, 0, -4.4);
    this.scene.add(bench);
    const crate = (x: number, y: number, z: number, r: number) => {
      const c = this.add(new THREE.BoxGeometry(1.05, 1.05, 1.05), wood, x, y, z);
      c.rotation.y = r;
    };
    crate(9.6, 0.53, 4.9, 0.3);
    crate(10.9, 0.53, 4.3, -0.2);
    crate(10.2, 1.58, 4.6, 0.6);
    const rock = this.mat(C.rock, { flat: true });
    const rnd = seeded(21);
    for (const [x, z] of [
      [-4.6, 5.4],
      [3.2, 6.6],
      [6.9, 2.4],
      [-8.6, -0.6],
      [13.4, 8.6],
      [-12.4, 1.2],
    ]) {
      const s = this.add(new THREE.IcosahedronGeometry(0.24 + rnd() * 0.16, 0), rock, x, 0.16, z);
      s.rotation.set(rnd() * 3, rnd() * 3, rnd() * 3);
    }
  }

  private word(): void {
    const font = new Font(fontData as unknown as ConstructorParameters<typeof Font>[0]);
    const material = this.mat(C.letters);
    const rows = this.portrait ? ["HEARTH", "SIDE"] : ["HEARTHSIDE"];
    for (const l of this.letters) this.scene.remove(l.mesh);
    this.letters = [];
    const size = 1.9;
    const group = new THREE.Group();
    let index = 0;
    rows.forEach((row, r) => {
      const glyphs = [...row].map((ch) => {
        const g = this.keep(new TextGeometry(ch, { font, size, depth: 0.95, curveSegments: 6, bevelEnabled: true, bevelThickness: 0.07, bevelSize: 0.05, bevelSegments: 3 }));
        g.computeBoundingBox();
        return g;
      });
      const gap = 0.2;
      const widths = glyphs.map((g) => g.boundingBox!.max.x - g.boundingBox!.min.x);
      const total = widths.reduce((a, b) => a + b, 0) + gap * (glyphs.length - 1);
      let x = -total / 2;
      glyphs.forEach((g, i) => {
        const mesh = new THREE.Mesh(g, material);
        mesh.castShadow = true;
        mesh.receiveShadow = true;
        mesh.position.set(x - g.boundingBox!.min.x, 0.07, r * 3.3);
        mesh.userData.restY = 0.07;
        x += widths[i] + gap;
        group.add(mesh);
        this.letters.push({ mesh, delay: 0.25 + index++ * 0.085 });
      });
    });
    group.position.set(this.portrait ? 0 : 0.9, 0, this.portrait ? -0.6 : 0.6);
    group.rotation.y = this.portrait ? -0.08 : -0.3;
    group.name = "word";
    const old = this.scene.getObjectByName("word");
    if (old) this.scene.remove(old);
    this.scene.add(group);
    this.started = performance.now();
  }

  private people(): void {
    const spots: [number, number, number][] = [
      [-5.2, 4.4, 0.3],
      [-3.7, 5.1, 0.1],
      [-2.2, 4.7, -0.15],
    ];
    NEIGHBOURS.forEach((look, i) => {
      const figure = buildResident(look, `title-${i}`);
      figure.root.traverse((o) => {
        o.castShadow = true;
      });
      figure.root.position.set(spots[i][0], 0, spots[i][1]);
      figure.root.rotation.y = spots[i][2];
      figure.root.scale.setScalar(1.75);
      this.scene.add(figure.root);
      this.figures.push(figure.root);
    });
  }

  // ------------------------------------------------------------------ view
  private onPointer = (e: PointerEvent): void => {
    this.pointer.set((e.clientX / window.innerWidth) * 2 - 1, (e.clientY / window.innerHeight) * 2 - 1);
  };

  private onVisibility = (): void => {
    if (document.visibilityState === "visible" && !this.frame) this.tick();
  };

  private resize(): void {
    const w = this.canvas.clientWidth || 1;
    const h = this.canvas.clientHeight || 1;
    const portrait = w / h < 0.85;
    if (portrait !== this.portrait) {
      this.portrait = portrait;
      this.word();
      this.figures.forEach((f, i) => f.position.set(portrait ? -1.6 + i * 1.6 : [-5.2, -3.7, -2.2][i], 0, portrait ? 6.6 : [4.4, 5.1, 4.7][i]));
    }
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    // wide screens look across the word from the front left; tall ones stand further back and higher
    const wide = Math.min(1, Math.max(0, (w / h - 0.85) / 0.9));
    this.camera.fov = portrait ? 44 : 30;
    this.home.set(portrait ? -2.5 : -3.5, portrait ? 20 : 13.2, portrait ? 28 : 24 + (1 - wide) * 9);
    this.look.set(portrait ? 0 : 0.6, 0.5, portrait ? 1.6 : 0.4);
    // the menu sits at the bottom, so the world is framed a little above the middle
    this.camera.setViewOffset(w, h, 0, Math.round(h * 0.09), w, h);
    this.camera.updateProjectionMatrix();
    this.render(performance.now());
  }

  private render(now: number): void {
    const t = (now - this.started) / 1000;
    for (const { mesh, delay } of this.letters) {
      const k = this.reduce ? 1 : Math.min(1, Math.max(0, (t - delay) / 0.9));
      mesh.position.y = mesh.userData.restY + (1 - easeOutBounce(k)) * 9;
      mesh.visible = this.reduce || t >= delay;
    }
    if (!this.reduce) {
      this.figures.forEach((f, i) => (f.position.y = Math.abs(Math.sin(t * 2.2 + i * 1.3)) * 0.07));
      this.glows.forEach((g, i) => (g.intensity = 9 + Math.sin(t * 7 + i * 2) * 0.9));
      for (const s of this.streaks) s.position.x += Math.sin(t * 0.6 + s.userData.phase) * 0.004;
    }
    this.eased.lerp(this.pointer, 0.045);
    const sway = this.reduce ? 0 : Math.sin(t * 0.25) * 0.5;
    this.camera.position.set(this.home.x + sway + this.eased.x * 1.4, this.home.y - this.eased.y * 0.7, this.home.z);
    this.camera.lookAt(this.look);
    this.renderer.render(this.scene, this.camera);
  }

  private tick = (): void => {
    this.frame = 0;
    if (document.visibilityState !== "visible") return;
    const now = performance.now();
    this.render(now);
    const settled = this.reduce && now - this.started > 400;
    if (!settled) this.frame = requestAnimationFrame(this.tick);
  };

  /** Free the graphics memory before the town itself starts drawing. */
  dispose(): void {
    cancelAnimationFrame(this.frame);
    this.observer.disconnect();
    window.removeEventListener("pointermove", this.onPointer);
    document.removeEventListener("visibilitychange", this.onVisibility);
    for (const x of this.owned) x.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
  }
}
