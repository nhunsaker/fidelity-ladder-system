// Acme — the neutral target app expeditions modify. Built on @metatoy/bootstrap-styled.
// Environment is inferred from the hostname (stage.* / prod.*; dev counts as stage);
// flags load at runtime from /flags.json, so one build serves every env — the flag file
// deployed NEXT TO the build is what differs (rung 5's staged flip).
import {
  Badge,
  Box,
  BsIconSearch,
  Button,
  Card,
  CardBody,
  CardTitle,
  Container,
  Display,
  FormControl,
  InputGroup,
  InputGroupText,
  Navbar,
  NavbarBrand,
  NavbarText,
  Small,
  Table,
} from '@metatoy/bootstrap-styled'
import React, { useEffect, useRef, useState } from 'react'
import { flagEnabled } from './flags.mjs'

function envFromHost() {
  const h = window.location.hostname
  if (h.startsWith('prod.')) return 'prod'
  return 'stage' // stage.* and local dev
}

const PRODUCTS = [
  { sku: 'AC-1001', name: 'Anvil, classic', price: '$49.00', stock: 12 },
  { sku: 'AC-1002', name: 'Rocket skates', price: '$129.00', stock: 3 },
  { sku: 'AC-1003', name: 'Giant magnet', price: '$89.00', stock: 7 },
  { sku: 'AC-1004', name: 'Portable hole', price: '$249.00', stock: 1 },
]

function Stat({ label, children }) {
  return (
    <Card style={{ flex: 1 }}>
      <CardBody>
        <CardTitle>{label}</CardTitle>
        <Display size={6} as="div" style={{ marginBottom: 0 }}>{children}</Display>
      </CardBody>
    </Card>
  )
}

export default function App() {
  const [flags, setFlags] = useState(null)
  const [query, setQuery] = useState('')
  const searchRef = useRef(null)
  const env = envFromHost()
  const cmdK = flagEnabled(flags, 'cmd-k-search', env)

  useEffect(() => {
    fetch('/flags.json').then((r) => r.json()).then(setFlags).catch(() => setFlags({}))
  }, [])

  // The shipped-behind-a-flag feature (expedition #101): ⌘K focuses search from anywhere.
  useEffect(() => {
    if (!cmdK) return undefined
    const h = (ev) => {
      if ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'k') {
        ev.preventDefault()
        searchRef.current?.focus()
      }
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [cmdK])

  const shown = PRODUCTS.filter((p) => p.name.toLowerCase().includes(query.toLowerCase()))

  return (
    <>
      <Navbar bg="dark" variant="dark" style={{ paddingLeft: 16, paddingRight: 16, display: 'flex', alignItems: 'center', gap: 16 }}>
        <NavbarBrand href="#">Acme</NavbarBrand>
        <InputGroup style={{ maxWidth: 360, marginLeft: 'auto' }}>
          <InputGroupText aria-hidden="true"><BsIconSearch /></InputGroupText>
          <FormControl
            ref={searchRef}
            placeholder={cmdK ? 'Search products (⌘K)' : 'Search products'}
            aria-label="Search products"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </InputGroup>
        <NavbarText>{env}</NavbarText>
      </Navbar>

      <Container style={{ paddingTop: 24, paddingBottom: 24 }}>
        <Box style={{ display: 'flex', gap: 16 }} mb={4}>
          <Stat label="Orders today">28</Stat>
          <Stat label="Revenue">$3,912</Stat>
          <Stat label="Low stock">2 <Badge variant="warning">check</Badge></Stat>
        </Box>

        <Card>
          <CardBody>
            <CardTitle style={{ marginBottom: 12 }}>Products</CardTitle>
            <Table hover responsive>
              <thead>
                <tr><th>SKU</th><th>Name</th><th>Price</th><th>Stock</th><th aria-label="actions" /></tr>
              </thead>
              <tbody>
                {shown.map((p) => (
                  <tr key={p.sku}>
                    <td><Small>{p.sku}</Small></td>
                    <td>{p.name}</td>
                    <td>{p.price}</td>
                    <td>{p.stock === 1 ? <Badge variant="danger">1 left</Badge> : p.stock}</td>
                    <td><Button size="sm" variant="outline-primary">Restock</Button></td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <Small>
              {shown.length} of {PRODUCTS.length} products
              {flags == null ? ' · loading flags…' : cmdK ? ' · ⌘K enabled' : ''}
            </Small>
          </CardBody>
        </Card>
      </Container>
    </>
  )
}
