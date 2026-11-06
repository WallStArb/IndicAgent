"use client";

import { useEffect, useRef } from "react";

interface Node {
  x: number;
  y: number;
  label: string;
  tier: number;
  pulse: number;
}

// Each particle follows an explicit path through node indices,
// advancing edge-by-edge rather than jumping across connections.
interface Particle {
  x: number;
  y: number;
  path: number[];      // ordered node indices, e.g. [0, 1, 2, 4, 6, 7]
  pathIndex: number;   // current edge: path[pathIndex] → path[pathIndex+1]
  edgeProgress: number; // 0..1 within the current edge
  speed: number;
}

// node indices: 0=Ingest, 1=Features, 2=Regimes, 3=Measure, 4=Research, 5=Book, 6=Shadow
const PATHS: number[][] = [
  [0, 1, 2, 4, 5, 6], // Ingest -> Features -> Regimes -> Research -> Book -> Shadow
  [0, 1, 3, 4, 5, 6], // Ingest -> Features -> Measure -> Research -> Book -> Shadow
  [0, 1, 4, 5, 6],    // Features feed Research directly
];

export function PipelineAnimation() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animationRef = useRef<number | undefined>(undefined);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const resize = () => {
      const parent = canvas.parentElement;
      if (parent) {
        canvas.width = parent.clientWidth;
        canvas.height = parent.clientHeight;
      }
    };
    resize();
    window.addEventListener("resize", resize);

    // ingest -> feature -> (regime / measure) -> research -> book -> forward shadow
    const nodes: Node[] = [
      { x: 0.07, y: 0.50, label: "Ingest",   tier: 0, pulse: 0.0 },
      { x: 0.25, y: 0.50, label: "Features", tier: 1, pulse: 0.4 },
      { x: 0.44, y: 0.30, label: "Regimes",  tier: 2, pulse: 0.5 },
      { x: 0.44, y: 0.70, label: "Measure",  tier: 2, pulse: 0.3 },
      { x: 0.65, y: 0.50, label: "Research", tier: 3, pulse: 0.7 },
      { x: 0.81, y: 0.50, label: "Book",     tier: 4, pulse: 0.4 },
      { x: 0.94, y: 0.50, label: "Shadow",   tier: 5, pulse: 0.2 },
    ];

    const connections: Array<[number, number]> = [
      [0, 1],           // Ingest -> Features
      [1, 2], [1, 3],   // Features -> Regimes, Measure
      [1, 4],           // Features -> Research
      [2, 4], [3, 4],   // Regimes, Measure -> Research
      [4, 5],           // Research -> Book
      [5, 6],           // Book -> Shadow
    ];

    const particles: Particle[] = [];
    const maxParticles = 30;

    const spawnParticle = () => {
      const path = PATHS[Math.floor(Math.random() * PATHS.length)];
      particles.push({
        x: nodes[path[0]].x,
        y: nodes[path[0]].y,
        path,
        pathIndex: 0,
        edgeProgress: 0,
        speed: 0.008 + Math.random() * 0.012,
      });
    };

    const animate = () => {
      ctx.fillStyle = "#0A0E14";
      ctx.fillRect(0, 0, canvas.width, canvas.height);

      const w = canvas.width;
      const h = canvas.height;

      // Draw connections
      ctx.strokeStyle = "rgba(78, 214, 200, 0.1)";
      ctx.lineWidth = 1;
      connections.forEach(([fromIdx, toIdx]) => {
        const from = nodes[fromIdx];
        const to = nodes[toIdx];
        ctx.beginPath();
        ctx.moveTo(from.x * w, from.y * h);
        ctx.lineTo(to.x * w, to.y * h);
        ctx.stroke();
      });

      // Draw nodes
      nodes.forEach((node) => {
        node.pulse = (node.pulse + 0.02) % (Math.PI * 2);
        const x = node.x * w;
        const y = node.y * h;
        const pulseIntensity = 0.5 + Math.sin(node.pulse) * 0.5;

        const gradient = ctx.createRadialGradient(x, y, 0, x, y, 30);
        gradient.addColorStop(0, `rgba(78, 214, 200, ${0.3 * pulseIntensity})`);
        gradient.addColorStop(1, "rgba(78, 214, 200, 0)");
        ctx.fillStyle = gradient;
        ctx.beginPath();
        ctx.arc(x, y, 30, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = "#4ED6C8";
        ctx.beginPath();
        ctx.arc(x, y, 6, 0, Math.PI * 2);
        ctx.fill();

        ctx.fillStyle = "rgba(228, 232, 239, 0.8)";
        ctx.font = "12px JetBrains Mono";
        ctx.textAlign = "center";
        ctx.fillText(node.label, x, y - 15);
      });

      // Spawn particles
      if (particles.length < maxParticles && Math.random() < 0.1) {
        spawnParticle();
      }

      // Update and draw particles
      for (let i = particles.length - 1; i >= 0; i--) {
        const p = particles[i];
        p.edgeProgress += p.speed;

        if (p.edgeProgress >= 1) {
          p.pathIndex++;
          if (p.pathIndex >= p.path.length - 1) {
            particles.splice(i, 1);
            continue;
          }
          p.edgeProgress -= 1;
        }

        const fromNode = nodes[p.path[p.pathIndex]];
        const toNode = nodes[p.path[p.pathIndex + 1]];

        p.x = fromNode.x + (toNode.x - fromNode.x) * p.edgeProgress;
        p.y = fromNode.y + (toNode.y - fromNode.y) * p.edgeProgress;

        ctx.fillStyle = `rgba(212, 168, 75, ${0.8 - p.edgeProgress * 0.5})`;
        ctx.beginPath();
        ctx.arc(p.x * w, p.y * h, 3, 0, Math.PI * 2);
        ctx.fill();

        ctx.strokeStyle = `rgba(212, 168, 75, ${0.4 - p.edgeProgress * 0.3})`;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(fromNode.x * w, fromNode.y * h);
        ctx.lineTo(p.x * w, p.y * h);
        ctx.stroke();
      }

      animationRef.current = requestAnimationFrame(animate);
    };

    animate();

    return () => {
      window.removeEventListener("resize", resize);
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="absolute inset-0 w-full h-full"
      style={{ background: "var(--landing-bg)" }}
    />
  );
}
