FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY *.go ./
RUN CGO_ENABLED=0 go build -o /agent .

FROM alpine:3.20
WORKDIR /app
COPY --from=build /agent /app/agent
EXPOSE 9100
ENTRYPOINT ["/app/agent"]
