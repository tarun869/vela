module github.com/vela/vela-go

go 1.22

// No external dependencies yet — the calculator and HTTP server are pure stdlib.
// Run `make proto` to generate gRPC stubs; that step will add:
//   google.golang.org/grpc v1.64.0
//   google.golang.org/protobuf v1.34.2
