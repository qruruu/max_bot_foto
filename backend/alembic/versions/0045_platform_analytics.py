"""Owner analytics, private security events and operational samples."""
from alembic import op

revision = '0045'
down_revision = '0044'
branch_labels = None
depends_on = None

# Frozen DDL: later model changes cannot alter this historical migration.
DDL = ['CREATE TABLE platform_analytics_state (\n'
 '\tid SERIAL NOT NULL, \n'
 '\tstarted_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, \n'
 '\tPRIMARY KEY (id)\n'
 ')',
 'CREATE TABLE platform_visits (\n'
 '\tid VARCHAR(36) NOT NULL, \n'
 '\tproduct VARCHAR(10) NOT NULL, \n'
 '\tvisitor_key VARCHAR(64) NOT NULL, \n'
 '\tsource VARCHAR(20) NOT NULL, \n'
 '\treferrer_host VARCHAR(253) NOT NULL, \n'
 '\tdevice VARCHAR(15) NOT NULL, \n'
 '\tstarted_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tlast_seen_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id)\n'
 ')',
 'CREATE INDEX ix_platform_visits_last_seen_at ON platform_visits (last_seen_at)',
 'CREATE INDEX ix_platform_visits_period ON platform_visits (product, started_at)',
 'CREATE INDEX ix_platform_visits_visitor_key ON platform_visits (visitor_key)',
 'CREATE TABLE platform_page_views (\n'
 '\tid VARCHAR(36) NOT NULL, \n'
 '\tvisit_id VARCHAR(36) NOT NULL, \n'
 '\tpage VARCHAR(30) NOT NULL, \n'
 '\tat TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(visit_id) REFERENCES platform_visits (id) ON DELETE CASCADE\n'
 ')',
 'CREATE INDEX ix_platform_page_views_at ON platform_page_views (at)',
 'CREATE INDEX ix_platform_page_views_visit_id ON platform_page_views (visit_id)',
 'CREATE TABLE platform_activity (\n'
 '\tday DATE NOT NULL, \n'
 '\tactor_key VARCHAR(64) NOT NULL, \n'
 '\torganization_id VARCHAR(36), \n'
 '\tkind VARCHAR(20) NOT NULL, \n'
 '\tlast_seen_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tPRIMARY KEY (day, actor_key), \n'
 '\tFOREIGN KEY(organization_id) REFERENCES organizations (id)\n'
 ')',
 'CREATE INDEX ix_platform_activity_organization_id ON platform_activity (organization_id)',
 'CREATE TABLE platform_request_minutes (\n'
 '\tminute TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tproduct VARCHAR(10) NOT NULL, \n'
 '\trequests INTEGER NOT NULL, \n'
 '\terrors INTEGER NOT NULL, \n'
 '\trejected INTEGER NOT NULL, \n'
 '\tduration_ms FLOAT NOT NULL, \n'
 '\tmaximum_ms FLOAT NOT NULL, \n'
 '\tbuckets JSONB NOT NULL, \n'
 '\tPRIMARY KEY (minute, product)\n'
 ')',
 'CREATE TABLE platform_samples (\n'
 '\tat TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tdata JSONB NOT NULL, \n'
 '\tPRIMARY KEY (at)\n'
 ')',
 'CREATE TABLE platform_runtime (\n'
 '\tkey VARCHAR(80) NOT NULL, \n'
 '\tsampled_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tdata JSONB NOT NULL, \n'
 '\tPRIMARY KEY (key)\n'
 ')',
 'CREATE TABLE platform_security_events (\n'
 '\tid VARCHAR(64) NOT NULL, \n'
 '\tat TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tlast_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tproduct VARCHAR(10) NOT NULL, \n'
 '\tkind VARCHAR(40) NOT NULL, \n'
 '\tip_address VARCHAR(45), \n'
 '\tactor_key VARCHAR(100) NOT NULL, \n'
 '\tactor_label VARCHAR(150) NOT NULL, \n'
 '\torganization_id VARCHAR(36), \n'
 '\tresource VARCHAR(100) NOT NULL, \n'
 '\tcount INTEGER NOT NULL, \n'
 '\tbytes_sent BIGINT NOT NULL, \n'
 '\tstatus_code INTEGER NOT NULL, \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(organization_id) REFERENCES organizations (id)\n'
 ')',
 'CREATE INDEX ix_platform_security_events_at ON platform_security_events (at)',
 'CREATE INDEX ix_platform_security_events_kind ON platform_security_events (kind)',
 'CREATE INDEX ix_security_actor_period ON platform_security_events (actor_key, at)',
 'CREATE INDEX ix_security_ip_period ON platform_security_events (ip_address, at)',
 'CREATE TABLE platform_security_alerts (\n'
 '\tid VARCHAR(64) NOT NULL, \n'
 '\tat TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tlast_at TIMESTAMP WITH TIME ZONE NOT NULL, \n'
 '\tcode VARCHAR(40) NOT NULL, \n'
 '\tseverity VARCHAR(15) NOT NULL, \n'
 '\tip_address VARCHAR(45), \n'
 '\tactor_label VARCHAR(150) NOT NULL, \n'
 '\torganization_id VARCHAR(36), \n'
 '\tsummary VARCHAR(500) NOT NULL, \n'
 '\tevidence JSONB NOT NULL, \n'
 '\treviewed_at TIMESTAMP WITH TIME ZONE, \n'
 '\tPRIMARY KEY (id), \n'
 '\tFOREIGN KEY(organization_id) REFERENCES organizations (id)\n'
 ')',
 'CREATE INDEX ix_platform_security_alerts_at ON platform_security_alerts (at)']


def upgrade():
    for statement in DDL:
        op.execute(statement)
    op.execute('INSERT INTO platform_analytics_state (id) VALUES (1)')


def downgrade():
    op.drop_table('platform_security_alerts')
    op.drop_table('platform_security_events')
    op.drop_table('platform_runtime')
    op.drop_table('platform_samples')
    op.drop_table('platform_request_minutes')
    op.drop_table('platform_activity')
    op.drop_table('platform_page_views')
    op.drop_table('platform_visits')
    op.drop_table('platform_analytics_state')
