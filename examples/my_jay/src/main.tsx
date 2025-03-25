import { createRoot } from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom';

import Speech2Tool from './Speech2Tool.tsx'



createRoot(document.getElementById('root')!).render(
  <BrowserRouter >
    <Routes>
      <Route path="/s2tool" element={<Speech2Tool />} />
    </Routes>
  </BrowserRouter>
)
