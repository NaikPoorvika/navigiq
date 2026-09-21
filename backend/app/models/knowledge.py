"""Bengaluru knowledge corpus for grounded answers (ADR-029).

Documents keep their provenance (source, URL, licence, retrieval time and a
content hash); chunks carry both a dense embedding (pgvector, 768 per
ADR-012) and a generated tsvector for sparse retrieval, fused with RRF.
"""
from sqlalchemy import (
    Column, Computed, DateTime, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from pgvector.sqlalchemy import Vector

from app.db.base_class import Base
from app.models.poi import EMBEDDING_DIM


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"
    id = Column(Integer, primary_key=True)
    source = Column(String(40), nullable=False)          # wikipedia | navigiq_guide | poi
    external_id = Column(String(200), nullable=False)    # title / guide key / poi id
    title = Column(Text, nullable=False)
    source_url = Column(Text)
    license = Column(String(120), nullable=False)
    doc_type = Column(String(30), nullable=False, default="article")
    poi_id = Column(Integer, ForeignKey("pois.id", ondelete="SET NULL"))
    content_hash = Column(String(64), nullable=False)
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)
    retrieved_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_knowledge_doc"),)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    id = Column(Integer, primary_key=True)
    document_id = Column(Integer, ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
                         nullable=False)
    chunk_index = Column(Integer, nullable=False)
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Vector(EMBEDDING_DIM))
    embedding_model = Column(String(80))
    content_hash = Column(String(64), nullable=False)
    tsv = Column(TSVECTOR, Computed("to_tsvector('english', chunk_text)", persisted=True))
    metadata_ = Column("metadata", JSONB, nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_index"),
        Index("ix_knowledge_chunks_tsv", "tsv", postgresql_using="gin"),
        Index("ix_knowledge_chunks_hnsw", "embedding", postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
    )
