// This page is superseded by Gallery which now includes hybrid search.
// Redirect to Gallery for any existing links.
import { useEffect } from 'react'
import { useNavigate } from 'react-router-dom'

export function Search() {
  const navigate = useNavigate()
  useEffect(() => { navigate('/', { replace: true }) }, [navigate])
  return null
}
