A table whose cells contain inline markup:

| API                      | Status      | Migration                                   |
| ------------------------ | ----------- | ------------------------------------------- |
| `GET /users`             | **Stable**  | No changes required                         |
| `POST /users`            | *Beta*      | Use `POST /v2/users` going forward          |
| `DELETE /users/:id`      | ~~Removed~~ | Replaced by `POST /users/:id/deactivate`    |
| `PATCH /users/:id/email` | ✅ Shipped   | Requires the new [scope guide](https://ex.co) |

Cells should render `inline code`, **bold**, *italic*, ~~strikethrough~~, emoji, and links at the same quality as body text.
