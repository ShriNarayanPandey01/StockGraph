import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';

export const PillarNarrativeVisual: React.FC = () => {
  const mountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = mountRef.current;
    if (!container) return;

    let width = container.clientWidth || 300;
    let height = container.clientHeight || 180;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
    camera.position.set(0, 3.8, 7.2);
    camera.lookAt(0, 0, 0);

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    const mainGroup = new THREE.Group();
    scene.add(mainGroup);

    // 1. Concentric L1-L4 Funnel Rings (Top)
    const funnelGroup = new THREE.Group();
    funnelGroup.position.set(0, 1.4, 0);
    mainGroup.add(funnelGroup);

    const ringRadii = [1.8, 1.35, 0.95, 0.55];
    const ringColors = [0x818cf8, 0xa855f7, 0xc084fc, 0xe879f9];
    const rings: THREE.Line[] = [];

    ringRadii.forEach((r, idx) => {
      const ringGeom = new THREE.BufferGeometry();
      const points: THREE.Vector3[] = [];
      const segments = 48;
      for (let i = 0; i <= segments; i++) {
        const theta = (i / segments) * Math.PI * 2;
        points.push(new THREE.Vector3(Math.cos(theta) * r, -idx * 0.15, Math.sin(theta) * r));
      }
      ringGeom.setFromPoints(points);
      const ringMat = new THREE.LineBasicMaterial({
        color: ringColors[idx],
        transparent: true,
        opacity: 0.65 - idx * 0.08,
      });
      const ringLine = new THREE.Line(ringGeom, ringMat);
      funnelGroup.add(ringLine);
      rings.push(ringLine);
    });

    // 2. 14-Day Trailing Narrative Helix
    const helixPoints: THREE.Vector3[] = [];
    const helixTurns = 2.4;
    const helixHeight = 2.8;
    const totalSamples = 80;

    for (let i = 0; i <= totalSamples; i++) {
      const t = i / totalSamples;
      const angle = t * Math.PI * 2 * helixTurns;
      const radius = 1.6 * (1 - t * 0.35);
      const x = Math.cos(angle) * radius;
      const y = 1.0 - t * helixHeight;
      const z = Math.sin(angle) * radius;
      helixPoints.push(new THREE.Vector3(x, y, z));
    }

    const helixGeom = new THREE.BufferGeometry().setFromPoints(helixPoints);
    const helixMat = new THREE.LineBasicMaterial({
      color: 0x9333ea,
      transparent: true,
      opacity: 0.45,
    });
    const helixLine = new THREE.Line(helixGeom, helixMat);
    mainGroup.add(helixLine);

    // 3. News Event Nodes (:NewsEvent) positioned along the helix
    const newsIndices = [8, 22, 38, 55, 72];
    const newsMeshes: THREE.Mesh[] = [];
    const newsGeom = new THREE.SphereGeometry(0.16, 16, 16);
    const newsMat = new THREE.MeshBasicMaterial({ color: 0xa855f7 });
    const duplicateMat = new THREE.MeshBasicMaterial({ color: 0x64748b }); // dropped duplicate

    newsIndices.forEach((idx, i) => {
      const pos = helixPoints[idx];
      const isDup = i === 1; // Simulated duplicate filtered out
      const mesh = new THREE.Mesh(newsGeom, isDup ? duplicateMat : newsMat);
      mesh.position.copy(pos);
      mainGroup.add(mesh);
      newsMeshes.push(mesh);
    });

    // 4. Cross-News Causal Chains ([:CORRELATED_WITH]) connecting event pairs across days
    const causalCurves: THREE.QuadraticBezierCurve3[] = [];
    const causalLines: THREE.Line[] = [];

    const pairs = [
      { from: 0, to: 2 },
      { from: 2, to: 3 },
      { from: 3, to: 4 },
    ];

    pairs.forEach((pair) => {
      const p1 = newsMeshes[pair.from].position;
      const p2 = newsMeshes[pair.to].position;
      const mid = new THREE.Vector3().addVectors(p1, p2).multiplyScalar(0.5);
      mid.x += 0.4; // arch outward
      mid.z += 0.4;

      const curve = new THREE.QuadraticBezierCurve3(p1, mid, p2);
      causalCurves.push(curve);

      const pts = curve.getPoints(24);
      const cGeom = new THREE.BufferGeometry().setFromPoints(pts);
      const cMat = new THREE.LineDashedMaterial({
        color: 0xe879f9,
        dashSize: 0.15,
        gapSize: 0.08,
        transparent: true,
        opacity: 0.75,
      });
      const cLine = new THREE.Line(cGeom, cMat);
      cLine.computeLineDistances();
      mainGroup.add(cLine);
      causalLines.push(cLine);
    });

    // 5. Causal Signal Pulses traversing between correlated news events
    const pulseGeom = new THREE.SphereGeometry(0.06, 8, 8);
    const pulseMat = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      blending: THREE.AdditiveBlending,
    });
    const pulseMeshes: { mesh: THREE.Mesh; curveIndex: number; progress: number }[] = [];

    causalCurves.forEach((_, cIdx) => {
      const pMesh = new THREE.Mesh(pulseGeom, pulseMat);
      mainGroup.add(pMesh);
      pulseMeshes.push({ mesh: pMesh, curveIndex: cIdx, progress: cIdx * 0.33 });
    });

    // Interactive mouse parallax
    let targetRotationX = 0;
    let targetRotationY = 0;

    const handleMouseMove = (e: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      const y = -(((e.clientY - rect.top) / rect.height) * 2 - 1);
      targetRotationY = x * 0.45;
      targetRotationX = y * 0.25;
    };

    container.addEventListener('mousemove', handleMouseMove);

    const handleResize = () => {
      if (!container) return;
      width = container.clientWidth || 300;
      height = container.clientHeight || 180;
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      renderer.setSize(width, height);
    };

    const resizeObserver = new ResizeObserver(() => handleResize());
    resizeObserver.observe(container);

    let animationId: number;
    const clock = new THREE.Clock();

    const animate = () => {
      animationId = requestAnimationFrame(animate);
      const delta = clock.getDelta();
      const elapsed = clock.getElapsedTime();

      // Ambient rotation + mouse parallax
      mainGroup.rotation.y += 0.006 + (targetRotationY - mainGroup.rotation.y) * 0.05;
      mainGroup.rotation.x += (targetRotationX - mainGroup.rotation.x) * 0.05;

      // Spin funnel rings at counter-speeds
      rings.forEach((r, idx) => {
        r.rotation.y += (idx % 2 === 0 ? 1 : -1) * 0.008;
      });

      // Animate causal pulses
      pulseMeshes.forEach((p) => {
        p.progress += delta * 0.55;
        if (p.progress > 1) p.progress = 0;
        const pt = causalCurves[p.curveIndex].getPoint(p.progress);
        p.mesh.position.copy(pt);
      });

      // Pulse news nodes
      newsMeshes.forEach((m, i) => {
        const s = 1 + Math.sin(elapsed * 3 + i) * 0.12;
        m.scale.set(s, s, s);
      });

      renderer.render(scene, camera);
    };

    animate();

    return () => {
      cancelAnimationFrame(animationId);
      container.removeEventListener('mousemove', handleMouseMove);
      resizeObserver.disconnect();
      if (renderer.domElement.parentElement) {
        renderer.domElement.parentElement.removeChild(renderer.domElement);
      }
      renderer.dispose();
      helixGeom.dispose();
      helixMat.dispose();
      newsGeom.dispose();
      newsMat.dispose();
      duplicateMat.dispose();
      pulseGeom.dispose();
      pulseMat.dispose();
      rings.forEach((r) => {
        r.geometry.dispose();
        (r.material as THREE.Material).dispose();
      });
      causalLines.forEach((l) => {
        l.geometry.dispose();
        (l.material as THREE.Material).dispose();
      });
    };
  }, []);

  return (
    <div className="relative w-full h-44 rounded-xl overflow-hidden bg-gradient-to-b from-ink-0/60 to-ink-1/90 border border-purple-500/15 group-hover:border-purple-500/35 transition-all">
      <div ref={mountRef} className="w-full h-full cursor-grab active:cursor-grabbing" />
      <div className="absolute top-2 left-2 flex items-center gap-1.5 px-2 py-0.5 rounded bg-black/60 border border-purple-500/30 text-[10px] font-mono text-purple-300 pointer-events-none">
        <span className="w-1.5 h-1.5 rounded-full bg-purple-400 animate-ping" />
        <span>L1-L4 Deduplication → Trailing 14D Helix</span>
      </div>
      <div className="absolute bottom-2 right-2 px-2 py-0.5 rounded bg-black/60 border border-purple-500/30 text-[9px] font-mono text-purple-300 pointer-events-none">
        [:CORRELATED_WITH] Causal Chains
      </div>
    </div>
  );
};

