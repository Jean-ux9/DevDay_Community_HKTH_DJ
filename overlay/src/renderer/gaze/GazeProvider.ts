export interface GazeSample { x: number; y: number; t: number; confidence: number }
export interface GazeProvider {
  start(): Promise<void>
  stop(): void
  onSample(callback: (sample: GazeSample) => void): () => void
}
