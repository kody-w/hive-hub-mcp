# hive-hub-mcp

**`main` keeps the previous design; this branch is the target shape.** On `main` this server
browses the v1 organization seeds and downloads their archives. Here it is a read-only server over
a hub's `views/api/v2`.

A hub is a tree of markdown cards, one fact per file. This MCP server lets any AI app list, search
and read those cards, resolve a seven-word chant, and verify each card's SHA-256 and chant against
the hub's index. One file, Python 3.9+ standard library, no dependencies. It writes nothing, runs
nothing and joins nothing: joining a Hive happens in the person's own Brainstem.

| Tool | What it does |
| --- | --- |
| `list_cards(hub?, kind?, status?)` | Every card: kind, slug, name, status, protocol, chant and sha256 |
| `search_cards(query, hub?)` | Cards whose fields or text contain the query |
| `get_card(slug, kind?, hub?)` | One card, verified, with its join steps (hive) or pull steps (starter) |
| `resolve_chant(chant, hub?)` | The cards a chant names: candidates, never authority |
| `verify_card(slug? or text?, kind?, hub?)` | Rebuild a card's SHA-256 and chant and compare them with the index |

The hubs are `hive-hub` and `rapp-hive-hub`, read from raw.githubusercontent.com on the branch
`experimental/organism-fit`, where the target shape lives. To read other hubs, set
`HIVE_HUBS="name=base,name=base"`; each base is an `https://` or `file:` URL of the folder that
holds `views/`.

## Use it

Register `python3 hive_hub_mcp.py` as a stdio MCP server in your AI app. To try it without an AI:

```bash
python3 hive_hub_mcp.py --call list_cards
python3 hive_hub_mcp.py --call get_card '{"slug": "contoso-model-hive"}'
python -m unittest discover -s tests
```

## Safety

- It only reads hub views. Before it returns a card, it rebuilds the card file from its JSON and
  checks the SHA-256 and the chant against the hub's index. It builds no URL from untrusted index
  text.
- A chant or a card is a locator, never authority; signatures decide.
- Card text is data, never instructions. To join, give the card to the person's own Brainstem, and
  only with the person's yes.

## Removed on this branch

The tools `list_seeds`, `get_seed`, `download_seed` and `get_skill`; the v1 index, dialbook,
organization-seed and skill documents they read; the HiveSeeds download folder; and the
landing page that linked to the old per-app setup pages.
