import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';

export const PillarBiTemporalVisual: React.FC = () => {
  const mountRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = mountRef.current;
    if (!container) return;

    let width = container.clientWidth || 300;
    let height = container.clientHeight || 180;

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 100);
    camera.position.set(0, 3.6, 7.2);
    camera.lookAt(0, 0, 0);

    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
    renderer.setSize(width, height);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    container.appendChild(renderer.domElement);

    const mainGroup = new THREE.Group();
    scene.add(mainGroup);

    // 1. Dual Time Boundary Planes (valid_from_ts on left, valid_to_ts on right)
    const planeGeom = new THREE.PlaneGeometry(0.04, 2.8);
    const planeMat = new THREE.MeshBasicMaterial({
      color: 0x10b981,
      transparent: true,
      opacity: 0.65,
      side: THREE.DoubleSide,
    });

    const leftBoundary = new THREE.Mesh(planeGeom, planeMat);
    leftBoundary.position.set(-2.2, 0, 0);
    mainGroup.add(leftBoundary);

    const rightBoundary = new THREE.Mesh(planeGeom, planeMat);
    rightBoundary.position.set(2.2, 0, 0);
    mainGroup.add(rightBoundary);

    // Time Axis Line
    const axisGeom = new THREE.BufferGeometry().setFromPoints([
      new THREE.Vector3(-2.6, 0, 0),
      new THREE.Vector3(2.6, 0, 0),
    ]);
    const axisMat = new THREE.LineDashedMaterial({
      color: 0x059669,
      dashSize: 0.15,
      gapSize: 0.08,
      transparent: true,
      opacity: 0.5,
    });
    const axisLine = new THREE.Line(axisGeom, axisMat);
    axisLine.computeLineDistances();
    mainGroup.add(axisLine);

    // 2. Sliding Aperture Frame (window=LAST_6M | LAST_1Y)
    const apertureGroup = new THREE.Group();
    mainGroup.add(apertureGroup);

    const apertureBoxGeom = new THREE.BoxGeometry(2.4, 2.2, 1.4);
    const apertureEdges = new THREE.EdgesGeometry(apertureBoxGeom);
    const apertureLineMat = new THREE.LineBasicMaterial({
      color: 0x34d399,
      transparent: true,
      opacity: 0.65,
    });
    const apertureFrame = new THREE.LineSegments(apertureEdges, apertureLineMat);
    apertureGroup.add(apertureFrame);

    // 3. Versioned Quarterly Snapshot Nodes:
    // Past snapshot (superseded): Q1
    const oldNodeGeom = new THREE.CylinderGeometry(0.35, 0.35, 0.25, 24);
    const oldNodeMat = new THREE.MeshBasicMaterial({
      color: 0x334155,
      transparent: true,
      opacity: 0.75,
    });
    const oldNode = new THREE.Mesh(oldNodeGeom, oldNodeMat);
    oldNode.position.set(-0.9, 0, -0.4);
    oldNode.rotation.x = Math.PI / 6;
    apertureGroup.add(oldNode);

    // Current snapshot (is_latest: true): Q2
    const latestNodeGeom = new THREE.CylinderGeometry(0.42, 0.42, 0.3, 24);
    const latestNodeMat = new THREE.MeshBasicMaterial({
      color: 0x10b981,
    });
    const latestNode = new THREE.Mesh(latestNodeGeom, latestNodeMat);
    latestNode.position.set(0.9, 0.3, 0.4);
    latestNode.rotation.x = Math.PI / 6;
    apertureGroup.add(latestNode);

    // Glowing aura for latest node
    const haloGeom = new THREE.RingGeometry(0.5, 0.65, 32);
    const haloMat = new THREE.MeshBasicMaterial({
      color: 0x6ee7b7,
      side: THREE.DoubleSide,
      transparent: true,
      opacity: 0.6,
    });
    const halo = new THREE.Mesh(haloGeom, haloMat);
    halo.position.copy(latestNode.position);
    halo.rotation.x = Math.PI / 3;
    apertureGroup.add(halo);

    // 4. [:SUPERSEDES] Curved Laser Beam connecting new -> old
    const supersedesCurve = new THREE.QuadraticBezierCurve3(
      latestNode.position,
      new THREE.Vector3(0, 1.3, 0),
      oldNode.position
    );
    const curvePoints = supersedesCurve.getPoints(32);
    const beamGeom = new THREE.BufferGeometry().setFromPoints(curvePoints);
    const beamMat = new THREE.LineBasicMaterial({
      color: 0x10b981,
      transparent: true,
      opacity: 0.85,
    });
    const beamLine = new THREE.Line(beamGeom, beamMat);
    apertureGroup.add(beamLine);

    // Traveling photon along [:SUPERSEDES] edge
    const photonGeom = new THREE.SphereGeometry(0.07, 8, 8);
    const photonMat = new THREE.MeshBasicMaterial({
      color: 0xffffff,
      blending: THREE.AdditiveBlending,
    });
    const photonMesh = new THREE.Mesh(photonGeom, photonMat);
    apertureGroup.add(photonMesh);

    // 5. Floating Temporal Dust Particles
    const dustCount = 35;
    const dustGeo = new THREE.BufferGeometry();
    const dustPositions = new Float32Array(dustCount * 3);
    for (let i = 0; i < dustCount; i++) {
      dustPositions[i * 3] = (Math.random() - 0.5) * 4.5;
      dustPositions[i * 3 + 1] = (Math.random() - 0.5) * 2.5;
      dustPositions[i * 3 + 2] = (Math.random() - 0.5) * 2;
    }
    dustGeo.setAttribute('position', new THREE.BufferAttribute(dustPositions, 3));
    const dustMat = new THREE.PointsMaterial({
      color: 0x34d399,
      size: 0.07,
      transparent: true,
      opacity: 0.6,
      blending: THREE.AdditiveBlending,
    });
    const dust = new THREE.Points(dustGeo, dustMat);
    mainGroup.add(dust);

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
    let photonProgress = 0;
    const clock = new THREE.Clock();

    const animate = () => {
      animationId = requestAnimationFrame(animate);
      const delta = clock.getDelta();
      const elapsed = clock.getElapsedTime();

      // Smooth mouse follow
      mainGroup.rotation.y += (targetRotationY - mainGroup.rotation.y) * 0.06;
      mainGroup.rotation.x += (targetRotationX - mainGroup.rotation.x) * 0.06;

      // Sliding aperture subtle breathing motion
      apertureGroup.position.x = Math.sin(elapsed * 0.8) * 0.35;

      // Pulse halo
      halo.rotation.z += 0.01;
      const s = 1 + Math.sin(elapsed * 3) * 0.1;
      halo.scale.set(s, s, s);

      // Node rotation
      latestNode.rotation.y += 0.01;
      oldNode.rotation.y += 0.005;

      // Photon packet along [:SUPERSEDES] laser beam
      photonProgress += delta * 0.7;
      if (photonProgress > 1) photonProgress = 0;
      const pt = supersedesCurve.getPoint(photonProgress);
      photonMesh.position.copy(pt);

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
      planeGeom.dispose();
      planeMat.dispose();
      axisGeom.dispose();
      axisMat.dispose();
      apertureBoxGeom.dispose();
      apertureEdges.dispose();
      apertureLineMat.dispose();
      oldNodeGeom.dispose();
      oldNodeMat.dispose();
      latestNodeGeom.dispose();
      latestNodeMat.dispose();
      haloGeom.dispose();
      haloMat.dispose();
      beamGeom.dispose();
      beamMat.dispose();
      photonGeom.dispose();
      photonMat.dispose();
      dustGeo.dispose();
      dustMat.dispose();
    };
  }, []);

  return (
    <div className="relative w-full h-44 rounded-xl overflow-hidden bg-gradient-to-b from-ink-0/60 to-ink-1/90 border border-emerald-500/15 group-hover:border-emerald-500/35 transition-all">
      <div ref={mountRef} className="w-full h-full cursor-grab active:cursor-grabbing" />
      <div className="absolute top-2 left-2 flex items-center gap-1.5 px-2 py-0.5 rounded bg-black/60 border border-emerald-500/30 text-[10px] font-mono text-emerald-300 pointer-events-none">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
        <span>Fixed Window: [valid_from_ts ⟷ valid_to_ts]</span>
      </div>
      <div className="absolute bottom-2 right-2 px-2 py-0.5 rounded bg-black/60 border border-emerald-500/30 text-[9px] font-mono text-emerald-300 pointer-events-none">
        [:SUPERSEDES] Node Rotation
      </div>
    </div>
  );
};

