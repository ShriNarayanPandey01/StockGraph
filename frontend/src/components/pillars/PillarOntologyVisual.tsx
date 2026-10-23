import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';

export const PillarOntologyVisual: React.FC = () => {
  const mountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = mountRef.current;
    if (!container) return;

    let width = container.clientWidth || 300;
    let height = container.clientHeight || 180;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
    camera.position.set(0, 3.5, 6.8);
    camera.lookAt(0, 0, 0);

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    const mainGroup = new THREE.Group();
    scene.add(mainGroup);

    // 1. Central Stock Core (:Stock {ticker: 'TATASTEEL'})
    const coreGeom = new THREE.SphereGeometry(0.55, 24, 24);
    const coreMat = new THREE.MeshBasicMaterial({
      color: 0xf59e0b,
      wireframe: false,
    });
    const coreMesh = new THREE.Mesh(coreGeom, coreMat);
    mainGroup.add(coreMesh);

    // Core Wireframe aura
    const auraGeom = new THREE.IcosahedronGeometry(0.72, 1);
    const auraMat = new THREE.MeshBasicMaterial({
      color: 0xfbbf24,
      wireframe: true,
      transparent: true,
      opacity: 0.5,
    });
    const auraMesh = new THREE.Mesh(auraGeom, auraMat);
    mainGroup.add(auraMesh);

    // 2. Injected Context Ring (StockContextCard orbit)
    const ringGeom = new THREE.RingGeometry(1.5, 1.55, 48);
    const ringMat = new THREE.MeshBasicMaterial({
      color: 0xd97706,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.4,
    });
    const contextRing = new THREE.Mesh(ringGeom, ringMat);
    contextRing.rotation.x = Math.PI / 2.3;
    mainGroup.add(contextRing);

    // 3. Satellite Entity Nodes:
    // S1: :Commodity (Coking Coal) - orange/amber
    // S2: :MacroFactor (RBI Repo) - purple
    // S3: :Stock (JSW Steel) - sky
    const satellites = [
      { id: 'COKING_COAL', pos: new THREE.Vector3(2.1, 0.4, -0.6), color: 0xf97316, radius: 0.32, label: 'COAL' },
      { id: 'RBI_REPO_RATE', pos: new THREE.Vector3(-1.9, 0.9, 0.5), color: 0xa855f7, radius: 0.3, label: 'REPO' },
      { id: 'JSWSTEEL', pos: new THREE.Vector3(0.2, -1.3, 1.6), color: 0x38bdf8, radius: 0.28, label: 'PEER' },
    ];

    const satelliteMeshes: THREE.Mesh[] = [];
    const curves: THREE.QuadraticBezierCurve3[] = [];
    const curveLines: THREE.Line[] = [];

    satellites.forEach((sat) => {
      // Mesh
      const satGeom = new THREE.SphereGeometry(sat.radius, 16, 16);
      const satMat = new THREE.MeshBasicMaterial({ color: sat.color });
      const satMesh = new THREE.Mesh(satGeom, satMat);
      satMesh.position.copy(sat.pos);
      mainGroup.add(satMesh);
      satelliteMeshes.push(satMesh);

      // Bezier curve to center
      const midPoint = new THREE.Vector3()
        .addVectors(coreMesh.position, sat.pos)
        .multiplyScalar(0.5);
      midPoint.y += 0.5; // arc upward

      const curve = new THREE.QuadraticBezierCurve3(coreMesh.position, midPoint, sat.pos);
      curves.push(curve);

      const curvePoints = curve.getPoints(24);
      const curveGeom = new THREE.BufferGeometry().setFromPoints(curvePoints);
      const curveLineMat = new THREE.LineBasicMaterial({
        color: sat.color,
        transparent: true,
        opacity: 0.4,
      });
      const line = new THREE.Line(curveGeom, curveLineMat);
      mainGroup.add(line);
      curveLines.push(line);
    });

    // 4. Photons / Energy Packets traversing the dynamic edges (simulating LLM transmission)
    const photonCount = 6;
    const photonGeom = new THREE.SphereGeometry(0.06, 8, 8);
    const photonMat = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      blending: THREE.AdditiveBlending,
    });
    const photonMeshes: { mesh: THREE.Mesh; curveIndex: number; progress: number; speed: number }[] = [];

    for (let i = 0; i < photonCount; i++) {
      const pMesh = new THREE.Mesh(photonGeom, photonMat);
      mainGroup.add(pMesh);
      photonMeshes.push({
        mesh: pMesh,
        curveIndex: i % curves.length,
        progress: (i / photonCount),
        speed: 0.45 + (i % 3) * 0.15,
      });
    }

    // Interactive mouse tilt
    let targetRotationX = 0;
    let targetRotationY = 0;

    const handleMouseMove = (e: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
      const y = -(((e.clientY - rect.top) / rect.height) * 2 - 1);
      targetRotationY = x * 0.5;
      targetRotationX = y * 0.3;
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

      // Slow ambient spin + mouse easing
      mainGroup.rotation.y += 0.005 + (targetRotationY - mainGroup.rotation.y) * 0.05;
      mainGroup.rotation.x += (targetRotationX - mainGroup.rotation.x) * 0.05;

      // Pulse core aura
      auraMesh.rotation.y += 0.01;
      auraMesh.rotation.x += 0.007;
      const scale = 1 + Math.sin(elapsed * 2.5) * 0.08;
      auraMesh.scale.set(scale, scale, scale);

      // Spin context ring
      contextRing.rotation.z += 0.008;

      // Animate photons along dynamic edges
      photonMeshes.forEach((p) => {
        p.progress += delta * p.speed;
        if (p.progress > 1) p.progress = 0;
        const curve = curves[p.curveIndex];
        const pt = curve.getPoint(p.progress);
        p.mesh.position.copy(pt);
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
      coreGeom.dispose();
      coreMat.dispose();
      auraGeom.dispose();
      auraMat.dispose();
      ringGeom.dispose();
      ringMat.dispose();
      photonGeom.dispose();
      photonMat.dispose();
      curveLines.forEach((l) => {
        l.geometry.dispose();
        (l.material as THREE.Material).dispose();
      });
      satelliteMeshes.forEach((m) => {
        m.geometry.dispose();
        (m.material as THREE.Material).dispose();
      });
    };
  }, []);

  return (
    <div className="relative w-full h-44 rounded-xl overflow-hidden bg-gradient-to-b from-ink-0/60 to-ink-1/90 border border-amber-500/15 group-hover:border-amber-500/35 transition-all">
      <div ref={mountRef} className="w-full h-full cursor-grab active:cursor-grabbing" />
      <div className="absolute top-2 left-2 flex items-center gap-1.5 px-2 py-0.5 rounded bg-black/60 border border-amber-500/30 text-[10px] font-mono text-amber-300 pointer-events-none">
        <span className="w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
        <span>Injected StockContextCard ⟷ Transmission</span>
      </div>
      <div className="absolute bottom-2 right-2 px-2 py-0.5 rounded bg-black/60 border border-amber-500/30 text-[9px] font-mono text-amber-300 pointer-events-none">
        Confidence Floor: ≥ 0.65
      </div>
    </div>
  );
};

