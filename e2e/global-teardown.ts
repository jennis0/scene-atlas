import fs from 'fs'
import path from 'path'

export default function globalTeardown() {
  const imageDir = path.resolve(__dirname, '.tmp-images')
  if (fs.existsSync(imageDir)) {
    fs.rmSync(imageDir, { recursive: true })
  }

  const tmpDataDir = path.resolve(__dirname, '.tmp-data')
  if (fs.existsSync(tmpDataDir)) {
    fs.rmSync(tmpDataDir, { recursive: true })
  }
}
