import {ThemeProvider, BaseStyles, Box, Header, TextInput} from '@primer/react'
import flags from '../flags.json'

// Neutral Acme surface. Expeditions add features here, gated by flags.json.
export default function App() {
  return (
    <ThemeProvider><BaseStyles>
      <Header>
        <Header.Item full>Acme</Header.Item>
        <Header.Item><TextInput aria-label="Search" placeholder="Search" /></Header.Item>
      </Header>
      <Box p={4}>Welcome to Acme. {/* expedition features render here */}</Box>
    </ThemeProvider></BaseStyles>
  )
}
export {flags}
